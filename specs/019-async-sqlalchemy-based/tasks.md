# Tasks: Async SQLAlchemy Support via PGWire

**Input**: Design documents from `/Users/tdyar/ws/iris-pgwire/specs/019-async-sqlalchemy-based/`
**Prerequisites**: plan.md (✅), spec.md (✅)
**Feature Branch**: `019-async-sqlalchemy-based`

## Execution Flow (main)
```
1. Load plan.md from feature directory
   → ✅ Loaded - Python 3.11+, SQLAlchemy 2.0+, psycopg 3.1+, FastAPI
2. Load optional design documents:
   → plan.md: Phase 2 contains full task breakdown
   → spec.md: 14 functional requirements, 5 acceptance scenarios
3. Generate tasks by category:
   → Setup: Verify baseline, document failures
   → Tests: Contract tests (5), FastAPI integration (2), IRIS features (3)
   → Core: Async dialect implementation (9 tasks)
   → Integration: FastAPI app, performance validation
   → Polish: Edge cases, documentation
4. Apply task rules:
   → Setup tasks: [P] (independent verification)
   → Contract tests: Sequential (same file)
   → Implementation: Sequential (same file: psycopg.py)
   → Feature tests: [P] (different files)
5. Number tasks sequentially (T001-T033)
6. Generate dependency graph
7. Create parallel execution examples
8. Validate task completeness:
   → ✅ All contracts have tests (5 contract tests)
   → ✅ All entities have implementation (IRISDialectAsync_psycopg)
   → ✅ All functional requirements covered
9. Return: SUCCESS (tasks ready for execution)
```

## Format: `[ID] [P?] Description`
- **[P]**: Can run in parallel (different files, no dependencies)
- Include exact file paths in descriptions

## Path Conventions
**Single Python library project** - extending existing sqlalchemy-iris package:
- **Package code**: `/Users/tdyar/ws/sqlalchemy-iris/sqlalchemy_iris/`
- **Benchmarks**: `/Users/tdyar/ws/iris-pgwire/benchmarks/`
- **Tests**: `/Users/tdyar/ws/iris-pgwire/tests/`
- **Docs**: `/Users/tdyar/ws/iris-pgwire/docs/`, `/Users/tdyar/ws/iris-pgwire/specs/019-async-sqlalchemy-based/`

---

## Phase 3.1: Setup & Baseline (Parallel Independent Verification)

- [X] **T001** [P] Verify sync SQLAlchemy benchmark passes
  - **File**: `/Users/tdyar/ws/iris-pgwire/benchmarks/sync_sqlalchemy_stress_test.py`
  - **Action**: Run sync benchmark to establish baseline performance metrics
  - **Success Criteria**: Benchmark completes without errors, documents latency per query
  - **Command**: `python3 benchmarks/sync_sqlalchemy_stress_test.py`
  - **Dependencies**: None (prerequisite verification)
  - **Note**: Baseline metrics known from previous testing (1-2ms simple, 5-10ms vector)

- [X] **T002** [P] Document current async SQLAlchemy failure modes
  - **File**: `/Users/tdyar/ws/iris-pgwire/specs/019-async-sqlalchemy-based/ASYNC_FAILURE_BASELINE.md`
  - **Action**: Run async benchmark (expected to fail), capture AwaitRequired errors, document stack traces
  - **Success Criteria**: Document shows exact error when calling `create_async_engine()` and `await conn.execute()`
  - **Command**: `python3 benchmarks/async_sqlalchemy_stress_test.py 2>&1 | head -100 > specs/019-async-sqlalchemy-based/ASYNC_FAILURE_BASELINE.md`
  - **Dependencies**: None (failure documentation)
  - **Status**: ✅ Documented expected AwaitRequired failure

---

## Phase 3.2: Tests First (TDD) ⚠️ MUST COMPLETE BEFORE 3.3
**CRITICAL: These tests MUST be written and MUST FAIL before ANY implementation**

### Contract Tests (Sequential - Same File)

- [X] **T003** Write contract test: `test_async_dialect_import_dbapi`
  - **File**: `/Users/tdyar/ws/iris-pgwire/tests/contract/test_async_dialect_contract.py`
  - **Action**: Write test that verifies `IRISDialectAsync_psycopg.import_dbapi()` returns psycopg module with `AsyncConnection` class
  - **Expected Result**: Test FAILS (class doesn't exist yet)
  - **Code Template**:
    ```python
    def test_async_dialect_import_dbapi():
        from sqlalchemy_iris.psycopg import IRISDialectAsync_psycopg
        dbapi = IRISDialectAsync_psycopg.import_dbapi()
        assert hasattr(dbapi, 'AsyncConnection'), "psycopg must have AsyncConnection"
    ```
  - **Dependencies**: None (first test)

- [ ] **T004** Write contract test: `test_async_engine_creation`
  - **File**: `/Users/tdyar/ws/iris-pgwire/tests/contract/test_async_dialect_contract.py` (same file as T003)
  - **Action**: Write test that creates async engine with `iris+psycopg://` URL and verifies `engine.dialect.is_async == True`
  - **Expected Result**: Test FAILS (AwaitRequired error or engine not async)
  - **Code Template**:
    ```python
    import pytest
    from sqlalchemy.ext.asyncio import create_async_engine

    @pytest.mark.asyncio
    async def test_async_engine_creation():
        engine = create_async_engine("iris+psycopg://localhost:5432/USER")
        assert engine.dialect.is_async == True, "Dialect must be async"
        await engine.dispose()
    ```
  - **Dependencies**: T003 (same file)

- [ ] **T005** Write contract test: `test_async_query_execution`
  - **File**: `/Users/tdyar/ws/iris-pgwire/tests/contract/test_async_dialect_contract.py` (same file as T004)
  - **Action**: Write test that executes simple async query `SELECT 1` and verifies result without AwaitRequired exception
  - **Expected Result**: Test FAILS (AwaitRequired exception)
  - **Code Template**:
    ```python
    @pytest.mark.asyncio
    async def test_async_query_execution():
        engine = create_async_engine("iris+psycopg://localhost:5432/USER")
        async with engine.connect() as conn:
            result = await conn.execute(text("SELECT 1"))
            assert result.scalar() == 1
        await engine.dispose()
    ```
  - **Dependencies**: T004 (same file)
  - **Note**: Requires PGWire server running on localhost:5432

- [ ] **T006** Write contract test: `test_async_bulk_insert`
  - **File**: `/Users/tdyar/ws/iris-pgwire/tests/contract/test_async_dialect_contract.py` (same file as T005)
  - **Action**: Write test that performs bulk insert of 100 records using `executemany` pattern and verifies completion in <10 seconds
  - **Expected Result**: Test FAILS (times out or takes 5+ minutes due to synchronous loop)
  - **Code Template**:
    ```python
    @pytest.mark.asyncio
    async def test_async_bulk_insert():
        import time
        from sqlalchemy import MetaData, Table, Column, Integer, String

        engine = create_async_engine("iris+psycopg://localhost:5432/USER")
        metadata = MetaData()
        test_table = Table('async_bulk_test', metadata,
            Column('id', Integer, primary_key=True),
            Column('name', String(16))
        )

        async with engine.begin() as conn:
            await conn.run_sync(metadata.drop_all)
            await conn.run_sync(metadata.create_all)

            start = time.time()
            await conn.execute(test_table.insert(), [
                {'name': f'record_{i}'} for i in range(100)
            ])
            elapsed = time.time() - start

            assert elapsed < 10, f"Bulk insert took {elapsed}s (should be <10s)"

        await engine.dispose()
    ```
  - **Dependencies**: T005 (same file)
  - **Note**: Validates FR-007 (no synchronous loop fallback)

- [ ] **T007** Write contract test: `test_async_performance_within_10_percent`
  - **File**: `/Users/tdyar/ws/iris-pgwire/tests/contract/test_async_dialect_contract.py` (same file as T006)
  - **Action**: Write test that compares async vs sync query latency over 1000 iterations and verifies async ≤ sync × 1.10
  - **Expected Result**: Test FAILS (async not implemented yet)
  - **Code Template**:
    ```python
    @pytest.mark.asyncio
    async def test_async_performance_within_10_percent():
        import time
        from sqlalchemy import create_engine

        # Sync baseline
        sync_engine = create_engine("iris+psycopg://localhost:5432/USER")
        sync_times = []
        with sync_engine.connect() as conn:
            for _ in range(1000):
                start = time.perf_counter()
                conn.execute(text("SELECT 1"))
                sync_times.append(time.perf_counter() - start)
        sync_avg = sum(sync_times) / len(sync_times)

        # Async test
        async_engine = create_async_engine("iris+psycopg://localhost:5432/USER")
        async_times = []
        async with async_engine.connect() as conn:
            for _ in range(1000):
                start = time.perf_counter()
                await conn.execute(text("SELECT 1"))
                async_times.append(time.perf_counter() - start)
        async_avg = sum(async_times) / len(async_times)

        threshold = sync_avg * 1.10
        assert async_avg <= threshold, f"Async {async_avg*1000:.2f}ms > Sync {sync_avg*1000:.2f}ms × 1.10 = {threshold*1000:.2f}ms"

        sync_engine.dispose()
        await async_engine.dispose()
    ```
  - **Dependencies**: T006 (same file)
  - **Note**: Validates FR-013 (10% latency threshold)

### FastAPI Integration Tests (Parallel - Different Files)

- [ ] **T008** [P] Write FastAPI integration test: `test_fastapi_async_sqlalchemy_integration`
  - **File**: `/Users/tdyar/ws/iris-pgwire/tests/integration/test_fastapi_async_sqlalchemy.py`
  - **Action**: Write test that creates minimal FastAPI app with async SQLAlchemy dependency, calls GET endpoint, verifies database query executes
  - **Expected Result**: Test FAILS (async dialect not working yet)
  - **Code Template**:
    ```python
    import pytest
    from fastapi import FastAPI, Depends
    from fastapi.testclient import TestClient
    from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
    from sqlalchemy import text

    engine = create_async_engine("iris+psycopg://localhost:5432/USER")

    async def get_db():
        async with AsyncSession(engine) as session:
            yield session

    app = FastAPI()

    @app.get("/test")
    async def test_endpoint(db: AsyncSession = Depends(get_db)):
        result = await db.execute(text("SELECT 1 as value"))
        return {"value": result.scalar()}

    @pytest.mark.asyncio
    async def test_fastapi_async_sqlalchemy_integration():
        from httpx import AsyncClient
        async with AsyncClient(app=app, base_url="http://test") as client:
            response = await client.get("/test")
            assert response.status_code == 200
            assert response.json() == {"value": 1}
    ```
  - **Dependencies**: T007 (contract tests complete)
  - **Note**: Validates FR-014 (FastAPI compatibility)

- [ ] **T009** [P] Write FastAPI integration test: `test_fastapi_async_vector_query`
  - **File**: `/Users/tdyar/ws/iris-pgwire/tests/integration/test_fastapi_async_vector.py`
  - **Action**: Write test that creates FastAPI endpoint performing IRIS VECTOR similarity query asynchronously
  - **Expected Result**: Test FAILS (async dialect + VECTOR support not working)
  - **Code Template**:
    ```python
    @app.post("/search")
    async def vector_search(query_vector: list[float], db: AsyncSession = Depends(get_db)):
        vector_str = '[' + ','.join(map(str, query_vector)) + ']'
        result = await db.execute(text("""
            SELECT id, VECTOR_COSINE(embedding, TO_VECTOR(:vec, FLOAT)) as score
            FROM test_vectors
            ORDER BY score DESC
            LIMIT 5
        """), {"vec": vector_str})
        return [{"id": row.id, "score": row.score} for row in result.fetchall()]

    @pytest.mark.asyncio
    async def test_fastapi_async_vector_query():
        # Setup test vectors table first
        async with engine.begin() as conn:
            await conn.execute(text("DROP TABLE IF EXISTS test_vectors"))
            await conn.execute(text("CREATE TABLE test_vectors (id INT, embedding VECTOR(FLOAT, 3))"))
            await conn.execute(text("INSERT INTO test_vectors VALUES (1, TO_VECTOR('[0.1,0.2,0.3]', FLOAT))"))

        # Test vector search
        async with AsyncClient(app=app, base_url="http://test") as client:
            response = await client.post("/search", json=[0.1, 0.2, 0.3])
            assert response.status_code == 200
            results = response.json()
            assert len(results) > 0
            assert results[0]["id"] == 1
    ```
  - **Dependencies**: T007 (contract tests complete)
  - **Note**: Validates FR-004 (IRIS VECTOR type support in async mode)

---

## Phase 3.3: Core Implementation (ONLY after tests T003-T009 are failing)

### Async Dialect Implementation (Sequential - Same File: psycopg.py)

- [ ] **T010** Implement `get_async_dialect_cls()` method in `IRISDialect_psycopg`
  - **File**: `/Users/tdyar/ws/sqlalchemy-iris/sqlalchemy_iris/psycopg.py`
  - **Action**: Add `@classmethod get_async_dialect_cls(cls, url)` that returns `IRISDialectAsync_psycopg` class
  - **Success Criteria**: Method exists, returns proper class type
  - **Code Template**:
    ```python
    @classmethod
    def get_async_dialect_cls(cls, url):
        """Return async variant of this dialect for create_async_engine()."""
        return IRISDialectAsync_psycopg
    ```
  - **Dependencies**: T009 (all tests failing, ready for implementation)
  - **Note**: This is the KEY method that enables SQLAlchemy async resolution

- [ ] **T011** Create `IRISDialectAsync_psycopg` class skeleton
  - **File**: `/Users/tdyar/ws/sqlalchemy-iris/sqlalchemy_iris/psycopg.py` (same file as T010)
  - **Action**: Create class inheriting from both `IRISDialect` and `PGDialectAsync_psycopg`, set basic attributes
  - **Success Criteria**: Class exists, imports work, `is_async = True`
  - **Code Template**:
    ```python
    from sqlalchemy.dialects.postgresql.psycopg import PGDialectAsync_psycopg

    class IRISDialectAsync_psycopg(IRISDialect, PGDialectAsync_psycopg):
        """Async IRIS dialect using psycopg for PGWire protocol."""
        driver = "psycopg"
        is_async = True
        supports_statement_cache = True
        supports_native_boolean = True
    ```
  - **Dependencies**: T010 (same file)

- [ ] **T012** Configure DBAPI inheritance properly in `IRISDialectAsync_psycopg`
  - **File**: `/Users/tdyar/ws/sqlalchemy-iris/sqlalchemy_iris/psycopg.py` (same file as T011)
  - **Action**: Ensure DBAPI module properly inherited from `PGDialectAsync_psycopg` parent to avoid "Dialect does not have DBAPI established" error
  - **Success Criteria**: `create_async_engine()` succeeds without DBAPI errors
  - **Implementation Note**: Verify `import_dbapi()` returns same module as parent class
  - **Dependencies**: T011 (same file)

- [ ] **T013** Implement `import_dbapi()` override
  - **File**: `/Users/tdyar/ws/sqlalchemy-iris/sqlalchemy_iris/psycopg.py` (same file as T012)
  - **Action**: Override to explicitly return psycopg module (same as parent, ensures async mode)
  - **Success Criteria**: Returns psycopg module with `AsyncConnection` class
  - **Code Template**:
    ```python
    @classmethod
    def import_dbapi(cls):
        """Import psycopg (async PostgreSQL driver)"""
        import psycopg
        return psycopg
    ```
  - **Dependencies**: T012 (same file)

- [ ] **T014** Implement `get_pool_class()` override
  - **File**: `/Users/tdyar/ws/sqlalchemy-iris/sqlalchemy_iris/psycopg.py` (same file as T013)
  - **Action**: Override to return `AsyncAdaptedQueuePool` for async engine instances
  - **Success Criteria**: Async engine uses correct pool class
  - **Code Template**:
    ```python
    @classmethod
    def get_pool_class(cls, url):
        from sqlalchemy.pool import AsyncAdaptedQueuePool
        return AsyncAdaptedQueuePool
    ```
  - **Dependencies**: T013 (same file)
  - **Note**: Validates FR-005 (proper async connection pool)

- [ ] **T015** Implement `create_connect_args()` override
  - **File**: `/Users/tdyar/ws/sqlalchemy-iris/sqlalchemy_iris/psycopg.py` (same file as T014)
  - **Action**: Override to convert SQLAlchemy URL to psycopg async connection arguments (inherit from parent but ensure async mode)
  - **Success Criteria**: Connection arguments properly formatted for psycopg `AsyncConnection`
  - **Code Template**:
    ```python
    def create_connect_args(self, url):
        opts = url.translate_connect_args(username='user')
        opts.update(url.query)
        if 'port' not in opts and url.port is None:
            opts['port'] = 5432
        if 'database' in opts:
            opts['dbname'] = opts.pop('database')
        return [[], opts]
    ```
  - **Dependencies**: T014 (same file)

- [ ] **T016** Implement `on_connect()` override
  - **File**: `/Users/tdyar/ws/sqlalchemy-iris/sqlalchemy_iris/psycopg.py` (same file as T015)
  - **Action**: Override to skip IRIS-specific cursor checks (cursor.sqlcode, %CHECKPRIV) that don't exist in psycopg cursors
  - **Success Criteria**: Connection initialization succeeds without AttributeError
  - **Code Template**:
    ```python
    def on_connect(self):
        def on_connect_impl(conn):
            self._dictionary_access = False
            self.vector_cosine_similarity = None
        return on_connect_impl
    ```
  - **Dependencies**: T015 (same file)

- [ ] **T017** Implement `do_executemany()` for async bulk operations
  - **File**: `/Users/tdyar/ws/sqlalchemy-iris/sqlalchemy_iris/psycopg.py` (same file as T016)
  - **Action**: Override to execute bulk inserts efficiently without falling back to synchronous loop (use async cursor.execute() in loop)
  - **Success Criteria**: Bulk insert of 100 records completes in <10 seconds
  - **Code Template**:
    ```python
    def do_executemany(self, cursor, query, params, context=None):
        if query.endswith(";"):
            query = query[:-1]
        for param_set in params:
            cursor.execute(query, param_set)
    ```
  - **Dependencies**: T016 (same file)
  - **Note**: Validates FR-007 (efficient bulk inserts)

- [ ] **T018** Verify all contract tests (T003-T007) now pass
  - **File**: `/Users/tdyar/ws/iris-pgwire/tests/contract/test_async_dialect_contract.py`
  - **Action**: Run pytest on contract tests, verify all 5 tests pass
  - **Success Criteria**: All contract tests green, no AwaitRequired errors, performance within 10%
  - **Command**: `pytest tests/contract/test_async_dialect_contract.py -v`
  - **Dependencies**: T017 (implementation complete)
  - **GATE**: Must pass before proceeding to Phase 3.4

---

## Phase 3.4: Integration & Validation

### FastAPI Integration (Sequential - Depends on T018)

- [ ] **T019** Create FastAPI test application scaffold
  - **File**: `/Users/tdyar/ws/iris-pgwire/tests/integration/fastapi_test_app.py`
  - **Action**: Create minimal FastAPI app with async SQLAlchemy dependency injection for use in integration tests
  - **Success Criteria**: App runs, exposes endpoints, uses async SQLAlchemy session
  - **Code**:
    ```python
    from fastapi import FastAPI, Depends
    from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker
    from sqlalchemy import text

    engine = create_async_engine("iris+psycopg://localhost:5432/USER")
    AsyncSessionLocal = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async def get_db():
        async with AsyncSessionLocal() as session:
            yield session

    app = FastAPI()

    @app.get("/health")
    async def health(db: AsyncSession = Depends(get_db)):
        result = await db.execute(text("SELECT 1"))
        return {"status": "ok", "db": result.scalar() == 1}
    ```
  - **Dependencies**: T018 (contract tests passing)

- [ ] **T020** Verify FastAPI integration tests (T008-T009) now pass
  - **Files**:
    - `/Users/tdyar/ws/iris-pgwire/tests/integration/test_fastapi_async_sqlalchemy.py`
    - `/Users/tdyar/ws/iris-pgwire/tests/integration/test_fastapi_async_vector.py`
  - **Action**: Run pytest on FastAPI integration tests, verify both pass
  - **Success Criteria**: Both FastAPI tests green, async queries work, VECTOR queries work
  - **Command**: `pytest tests/integration/test_fastapi_*.py -v`
  - **Dependencies**: T019 (FastAPI app created)
  - **Note**: Validates FR-014 (FastAPI compatibility)

### Performance Validation (Sequential - Benchmarks)

- [ ] **T021** Run async vs sync benchmark (10,000 queries)
  - **Files**:
    - `/Users/tdyar/ws/iris-pgwire/benchmarks/async_sqlalchemy_stress_test.py`
    - `/Users/tdyar/ws/iris-pgwire/benchmarks/sync_sqlalchemy_stress_test.py`
  - **Action**: Run both benchmarks, collect latency metrics
  - **Success Criteria**: Both benchmarks complete without errors
  - **Commands**:
    ```bash
    python3 benchmarks/sync_sqlalchemy_stress_test.py > results_sync.txt
    python3 benchmarks/async_sqlalchemy_stress_test.py > results_async.txt
    ```
  - **Dependencies**: T020 (integration tests passing)

- [ ] **T022** Verify 10% latency threshold (FR-013)
  - **File**: `/Users/tdyar/ws/iris-pgwire/specs/019-async-sqlalchemy-based/PERFORMANCE_VALIDATION.md`
  - **Action**: Compare async vs sync benchmark results, calculate percentage difference, verify async ≤ sync × 1.10
  - **Success Criteria**: Document shows async latency within 10% of sync, includes graphs/tables
  - **Validation Formula**: `async_avg_latency <= sync_avg_latency * 1.10`
  - **Dependencies**: T021 (benchmarks run)
  - **GATE**: Must pass to meet FR-013 requirement

- [ ] **T023** Profile async overhead vs raw psycopg
  - **File**: `/Users/tdyar/ws/iris-pgwire/benchmarks/raw_psycopg_async_baseline.py`
  - **Action**: Create benchmark using raw psycopg `AsyncConnection` (no SQLAlchemy), compare overhead
  - **Success Criteria**: Documents SQLAlchemy async overhead, verifies <5ms constitutional limit
  - **Code Template**:
    ```python
    import asyncio
    import psycopg
    from time import perf_counter

    async def benchmark_raw_psycopg():
        conn = await psycopg.AsyncConnection.connect("host=localhost port=5432 dbname=USER")
        times = []
        for _ in range(10000):
            start = perf_counter()
            cur = await conn.execute("SELECT 1")
            times.append(perf_counter() - start)
        await conn.close()
        avg = sum(times) / len(times)
        print(f"Raw psycopg async: {avg*1000:.2f}ms average")

    asyncio.run(benchmark_raw_psycopg())
    ```
  - **Dependencies**: T022 (latency threshold verified)

- [ ] **T024** Document performance results
  - **File**: `/Users/tdyar/ws/iris-pgwire/specs/019-async-sqlalchemy-based/PERFORMANCE_RESULTS.md`
  - **Action**: Create final performance report with all metrics, graphs, analysis
  - **Success Criteria**: Document includes sync baseline, async performance, raw psycopg comparison, constitutional compliance analysis
  - **Contents**:
    - Sync baseline: X ms/query
    - Async performance: Y ms/query (within 10%? ✅/❌)
    - Raw psycopg: Z ms/query
    - SQLAlchemy overhead: (Y - Z) ms (< 5ms? ✅/❌)
    - Conclusion: FR-013 met, constitutional standard met
  - **Dependencies**: T023 (profiling complete)

---

## Phase 3.5: IRIS Feature Validation (Parallel - Different Test Files)

- [ ] **T025** [P] Test VECTOR type support in async mode
  - **File**: `/Users/tdyar/ws/iris-pgwire/tests/integration/test_async_iris_vector.py`
  - **Action**: Write test that creates VECTOR table, inserts vectors, performs VECTOR_COSINE queries asynchronously
  - **Success Criteria**: Test passes, VECTOR types work identically in async and sync modes
  - **Code Template**:
    ```python
    @pytest.mark.asyncio
    async def test_async_vector_type_support():
        engine = create_async_engine("iris+psycopg://localhost:5432/USER")
        async with engine.begin() as conn:
            await conn.execute(text("DROP TABLE IF EXISTS async_vectors"))
            await conn.execute(text("CREATE TABLE async_vectors (id INT, vec VECTOR(FLOAT, 128))"))

            # Insert vector
            vec_str = '[' + ','.join([str(random()) for _ in range(128)]) + ']'
            await conn.execute(text("INSERT INTO async_vectors VALUES (1, TO_VECTOR(:v, FLOAT))"), {"v": vec_str})

            # Query vector
            result = await conn.execute(text("SELECT VECTOR_COSINE(vec, TO_VECTOR(:q, FLOAT)) FROM async_vectors"), {"q": vec_str})
            score = result.scalar()
            assert score == 1.0, "Cosine similarity with self should be 1.0"

        await engine.dispose()
    ```
  - **Dependencies**: T024 (performance validated)
  - **Note**: Validates FR-004 (IRIS VECTOR type support)

- [ ] **T026** [P] Test INFORMATION_SCHEMA queries async
  - **File**: `/Users/tdyar/ws/iris-pgwire/tests/integration/test_async_iris_metadata.py`
  - **Action**: Write test that queries INFORMATION_SCHEMA tables asynchronously (same as sync SQLAlchemy does)
  - **Success Criteria**: Test passes, INFORMATION_SCHEMA accessible in async mode
  - **Code Template**:
    ```python
    @pytest.mark.asyncio
    async def test_async_information_schema():
        engine = create_async_engine("iris+psycopg://localhost:5432/USER")
        async with engine.connect() as conn:
            result = await conn.execute(text("""
                SELECT TABLE_NAME
                FROM INFORMATION_SCHEMA.TABLES
                WHERE TABLE_SCHEMA = 'SQLUser'
                LIMIT 5
            """))
            tables = [row[0] for row in result.fetchall()]
            assert len(tables) > 0, "Should find tables in INFORMATION_SCHEMA"
        await engine.dispose()
    ```
  - **Dependencies**: T024 (performance validated)
  - **Note**: Validates FR-004 (INFORMATION_SCHEMA queries)

- [ ] **T027** [P] Test IRIS function calls async
  - **File**: `/Users/tdyar/ws/iris-pgwire/tests/integration/test_async_iris_functions.py`
  - **Action**: Write test that calls IRIS-specific functions (CURRENT_TIMESTAMP, etc.) asynchronously
  - **Success Criteria**: Test passes, IRIS functions work in async mode
  - **Code Template**:
    ```python
    @pytest.mark.asyncio
    async def test_async_iris_functions():
        engine = create_async_engine("iris+psycopg://localhost:5432/USER")
        async with engine.connect() as conn:
            result = await conn.execute(text("SELECT CURRENT_TIMESTAMP"))
            timestamp = result.scalar()
            assert timestamp is not None

            result = await conn.execute(text("SELECT $HOROLOG"))
            horolog = result.scalar()
            assert horolog is not None
        await engine.dispose()
    ```
  - **Dependencies**: T024 (performance validated)
  - **Note**: Validates FR-004 (IRIS functions)

- [ ] **T028** Verify all FR-004 requirements pass
  - **Action**: Run all IRIS feature tests (T025-T027), verify complete IRIS feature parity between sync and async
  - **Success Criteria**: All 3 tests pass, document confirms FR-004 compliance
  - **Command**: `pytest tests/integration/test_async_iris_*.py -v`
  - **Dependencies**: T025, T026, T027 (all feature tests)
  - **GATE**: Must pass to meet FR-004 requirement

---

## Phase 3.6: Edge Cases & Error Handling

- [ ] **T029** Test async engine with sync code paths (FR-009 error detection)
  - **File**: `/Users/tdyar/ws/iris-pgwire/tests/integration/test_async_error_handling.py`
  - **Action**: Write test that attempts to use async engine with synchronous code, verifies clear error message
  - **Success Criteria**: Test passes, error message clearly states async engine requires await
  - **Code Template**:
    ```python
    def test_async_engine_with_sync_code():
        engine = create_async_engine("iris+psycopg://localhost:5432/USER")
        with pytest.raises(Exception) as exc_info:
            with engine.connect() as conn:  # Missing await
                conn.execute(text("SELECT 1"))

        error_msg = str(exc_info.value).lower()
        assert "await" in error_msg or "async" in error_msg, "Error should mention async requirement"
    ```
  - **Dependencies**: T028 (IRIS features validated)
  - **Note**: Validates FR-009 (clear error messages)

- [ ] **T030** Test missing psycopg async dependencies
  - **File**: `/Users/tdyar/ws/iris-pgwire/tests/integration/test_async_error_handling.py` (same file as T029)
  - **Action**: Write test that simulates missing psycopg[binary] extras, verifies helpful error message
  - **Success Criteria**: Test documents expected error when psycopg async not available
  - **Implementation Note**: May need to mock import failure
  - **Dependencies**: T029 (same file)

- [ ] **T031** Test transaction rollback in async context
  - **File**: `/Users/tdyar/ws/iris-pgwire/tests/integration/test_async_transactions.py`
  - **Action**: Write test that performs async transaction with rollback, verifies data not persisted
  - **Success Criteria**: Test passes, async rollback works correctly
  - **Code Template**:
    ```python
    @pytest.mark.asyncio
    async def test_async_transaction_rollback():
        engine = create_async_engine("iris+psycopg://localhost:5432/USER")

        # Start transaction
        async with engine.begin() as conn:
            await conn.execute(text("DROP TABLE IF EXISTS rollback_test"))
            await conn.execute(text("CREATE TABLE rollback_test (id INT)"))
            await conn.execute(text("INSERT INTO rollback_test VALUES (1)"))
            await conn.rollback()  # Explicit rollback

        # Verify table doesn't exist (transaction rolled back)
        async with engine.connect() as conn:
            with pytest.raises(Exception):  # Table should not exist
                await conn.execute(text("SELECT * FROM rollback_test"))

        await engine.dispose()
    ```
  - **Dependencies**: T030 (same file as previous error test)
  - **Note**: Validates FR-006 (async transaction management)

- [ ] **T032** Verify edge case acceptance scenarios
  - **File**: `/Users/tdyar/ws/iris-pgwire/specs/019-async-sqlalchemy-based/EDGE_CASE_VALIDATION.md`
  - **Action**: Review spec.md edge cases section, verify all 5 edge cases tested
  - **Success Criteria**: Document confirms:
    - ✅ Async engine with sync code paths (T029)
    - ✅ Connection pooling in async mode (implicit in all tests)
    - ✅ IRIS VECTOR types in async queries (T025)
    - ✅ psycopg sync-only mode detection (T030)
    - ✅ Transaction management in async context (T031)
  - **Dependencies**: T031 (all edge case tests complete)

- [ ] **T033** Final acceptance validation
  - **Action**: Run ALL tests (contract, integration, IRIS features, edge cases), verify complete feature implementation
  - **Success Criteria**: All 33 tasks complete, all tests pass, all 14 functional requirements validated
  - **Command**: `pytest tests/ -v --tb=short`
  - **Validation Checklist**:
    - ✅ FR-001: Async engine creation (T004, T018)
    - ✅ FR-002: No AwaitRequired errors (T005, T018)
    - ✅ FR-003: Async dialect resolution (T010-T012)
    - ✅ FR-004: IRIS features maintained (T025-T028)
    - ✅ FR-005: Async connection pool (T014)
    - ✅ FR-006: Async transactions (T031)
    - ✅ FR-007: Efficient bulk inserts (T006, T017)
    - ✅ FR-008: psycopg AsyncConnection (T003, T013)
    - ✅ FR-009: Clear error messages (T029-T030)
    - ✅ FR-010: Sync + async coexistence (implicit - both dialects exist)
    - ✅ FR-011: Async ORM support (T008, T020)
    - ✅ FR-012: Async cursor operations (all tests)
    - ✅ FR-013: 10% latency threshold (T007, T022)
    - ✅ FR-014: FastAPI validation (T008-T009, T020)
  - **Dependencies**: T032 (edge cases validated)
  - **FINAL GATE**: All requirements met, feature complete

---

## Dependencies Graph

```
Setup (Parallel):
T001 [P] ─┐
          ├─→ T003 (Start contract tests)
T002 [P] ─┘

Contract Tests (Sequential - Same File):
T003 → T004 → T005 → T006 → T007

FastAPI Tests (Parallel):
T007 ─┬─→ T008 [P]
      └─→ T009 [P]

Implementation (Sequential - Same File):
T009 → T010 → T011 → T012 → T013 → T014 → T015 → T016 → T017 → T018

Integration:
T018 → T019 → T020

Performance (Sequential):
T020 → T021 → T022 → T023 → T024

IRIS Features (Parallel):
T024 ─┬─→ T025 [P]
      ├─→ T026 [P]
      └─→ T027 [P] ─→ T028

Edge Cases (Sequential):
T028 → T029 → T030 → T031 → T032 → T033
```

---

## Parallel Execution Examples

### Setup Phase (T001-T002)
```bash
# Run both baseline tasks in parallel
Task: "Verify sync SQLAlchemy benchmark passes in benchmarks/sync_sqlalchemy_stress_test.py"
Task: "Document current async failure modes in specs/019-async-sqlalchemy-based/ASYNC_FAILURE_BASELINE.md"
```

### FastAPI Tests (T008-T009)
```bash
# Run both FastAPI tests in parallel after contract tests pass
Task: "Write FastAPI integration test in tests/integration/test_fastapi_async_sqlalchemy.py"
Task: "Write FastAPI vector test in tests/integration/test_fastapi_async_vector.py"
```

### IRIS Feature Tests (T025-T027)
```bash
# Run all IRIS feature validation tests in parallel
Task: "Test VECTOR type support in tests/integration/test_async_iris_vector.py"
Task: "Test INFORMATION_SCHEMA queries in tests/integration/test_async_iris_metadata.py"
Task: "Test IRIS function calls in tests/integration/test_async_iris_functions.py"
```

---

## Notes

- **[P] tasks** = different files, no dependencies, safe to parallelize
- **Sequential tasks** (no [P]) = same file or dependencies, must run in order
- **TDD Critical**: T003-T009 (tests) MUST complete and fail before T010-T018 (implementation)
- **Performance Gate**: T022 must pass (10% threshold) to meet FR-013
- **FastAPI Gate**: T020 must pass to meet FR-014
- **IRIS Gate**: T028 must pass to meet FR-004
- **Final Gate**: T033 validates all 14 functional requirements
- **Commit strategy**: Commit after each task for clean git history
- **PGWire dependency**: Most tests require PGWire server running on localhost:5432

---

## Task Generation Rules Applied

1. ✅ Each contract test → separate test task (T003-T007)
2. ✅ Entity (IRISDialectAsync_psycopg) → model creation tasks (T010-T017)
3. ✅ Each acceptance scenario → integration test (T008-T009, T025-T027)
4. ✅ Different files → marked [P] for parallel
5. ✅ Same file → sequential (no [P])
6. ✅ Tests before implementation (TDD strict)
7. ✅ Dependencies ordered correctly (setup → tests → core → integration → polish)
8. ✅ All 14 functional requirements mapped to validation tasks

---

**Total Tasks**: 33
**Estimated Parallel Groups**: 3 (Setup: 2, FastAPI: 2, IRIS: 3)
**Sequential Chains**: 5 (Contract tests: 5, Implementation: 9, Performance: 4, Edge cases: 5)

**Next Step**: Execute tasks T001-T033 in dependency order, verify all tests pass, validate all 14 functional requirements.

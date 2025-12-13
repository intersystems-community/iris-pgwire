# Implementation Plan: Benchmark Debug Capabilities and Vector Optimizer Fix

**Branch**: `016-add-requirements-to` | **Date**: 2025-10-03 | **Spec**: [spec.md](./spec.md)
**Input**: Feature specification from `/specs/016-add-requirements-to/spec.md`

## Execution Flow (/plan command scope)
```
1. Load feature spec from Input path ✅
   → Spec loaded successfully
2. Fill Technical Context ✅
   → Project Type: single (Python project)
   → Structure Decision: Existing benchmark infrastructure
3. Fill Constitution Check section ✅
   → Validates against constitution.md principles
4. Evaluate Constitution Check section ✅
   → No violations detected
   → Update Progress Tracking: Initial Constitution Check ✅
5. Execute Phase 0 → research.md ✅
   → All technical context already known (no NEEDS CLARIFICATION)
6. Execute Phase 1 → contracts, data-model.md, quickstart.md, CLAUDE.md ✅
7. Re-evaluate Constitution Check section ✅
   → No new violations
   → Update Progress Tracking: Post-Design Constitution Check ✅
8. Plan Phase 2 → Task generation approach described ✅
9. STOP - Ready for /tasks command ✅
```

## Summary

Fix critical vector optimizer bug causing IRIS compiler crashes, and add comprehensive debug capabilities to the 3-way benchmark suite. The vector optimizer currently strips brackets from vector literals during pgvector operator conversion (`TO_VECTOR('0.1,0.1,...', FLOAT)` instead of `TO_VECTOR('[0.1,0.1,...]', FLOAT)`), causing SQLCODE -400 errors. This blocks all vector similarity queries and prevents benchmark completion. The fix requires regex pattern correction, SQL validation before IRIS execution, and enhanced debug logging to identify future optimizer issues.

## Technical Context
**Language/Version**: Python 3.11
**Primary Dependencies**: psycopg (PostgreSQL client), intersystems-iris-dbapi, numpy, tabulate
**Storage**: IRIS database (vector tables), PostgreSQL (pgvector comparison)
**Testing**: pytest, contract tests, integration tests with real databases
**Target Platform**: Linux/macOS server, Docker containers (postgres-benchmark, iris-benchmark, pgwire-benchmark)
**Project Type**: single (Python project with benchmark infrastructure)
**Performance Goals**: 5ms query translation overhead (constitutional requirement), 4-10× HNSW improvement at 100K+ scale
**Constraints**: IRIS SQLCODE -400 compiler errors on malformed SQL, 3KB string literal limit in IRIS
**Scale/Scope**: 3-way database comparison (PostgreSQL, IRIS via PGWire, IRIS via DBAPI), 100-100K vector datasets

## Constitution Check
*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

**Principle I - Test-First Development**: ✅ PASS
- FR-009 requires dry-run mode for query validation
- FR-016 mandates correct result validation, not just performance
- Contract tests will validate SQL transformation correctness

**Principle II - Performance Requirements**: ✅ PASS
- FR-014 enforces 5ms translation overhead measurement
- FR-017 requires P50/P95/P99 latency percentiles
- Aligns with constitutional SLA: <5ms per query

**Principle III - IRIS Integration**: ✅ PASS
- FR-002 validates optimized SQL syntax before IRIS execution
- FR-003 captures IRIS error context (SQLCODE, error message)
- FR-004 implements timeout protection for compiler errors

**Principle IV - Phased Implementation**: ✅ PASS
- FR-013 supports incremental debugging (simple → vector → joins)
- Existing infrastructure allows isolated testing per query template

**Principle V - Constitutional Compliance**: ✅ PASS
- All requirements align with constitutional principles
- No deviations from established patterns

**Principle VI - Vector Performance**: ✅ PASS
- FR-015 ensures identical test data across all 3 methods
- FR-017 measures comparative performance metrics
- Supports HNSW validation at ≥100K scale

**Initial Check**: ✅ PASS (no violations)

## Project Structure

### Documentation (this feature)
```
specs/016-add-requirements-to/
├── plan.md              # This file
├── research.md          # Phase 0 output (minimal - no unknowns)
├── data-model.md        # Phase 1 output (debug entities)
├── quickstart.md        # Phase 1 output (validation procedure)
├── contracts/           # Phase 1 output (optimizer contract tests)
└── tasks.md             # Phase 2 output (/tasks command)
```

### Source Code (existing structure)
```
src/iris_pgwire/
├── vector_optimizer.py      # MODIFY: Fix bracket-stripping regex, add validation
├── protocol.py              # MODIFY: Add debug logging hooks
└── iris_executor.py         # MODIFY: Enhanced error context capture

benchmarks/
├── config.py                # MODIFY: Add debug configuration flags
├── 3way_comparison.py       # MODIFY: Add query trace logging
├── executors/
│   ├── pgwire_executor.py   # MODIFY: Query timeout protection
│   ├── postgres_executor.py # MODIFY: Consistent error handling
│   └── dbapi_executor.py    # MODIFY: Consistent error handling
└── output/
    ├── json_exporter.py     # MODIFY: Include optimization traces
    └── table_exporter.py    # MODIFY: Show debug metrics

tests/
├── contract/
│   └── test_vector_optimizer_syntax.py  # NEW: Validate bracket preservation
├── integration/
│   └── test_benchmark_debug.py          # NEW: Dry-run mode validation
└── unit/
    └── test_optimizer_validation.py     # NEW: SQL syntax validation
```

**Structure Decision**: Existing single-project Python structure. Benchmark infrastructure already established with Docker Compose orchestration. Changes focused on `src/iris_pgwire/vector_optimizer.py` (core fix) and `benchmarks/` directory (debug enhancements).

## Phase 0: Outline & Research

**No NEEDS CLARIFICATION detected** - all technical context is already known from:
1. Existing vector optimizer implementation (`src/iris_pgwire/vector_optimizer.py`)
2. Benchmark infrastructure (`benchmarks/` directory)
3. Diagnostic findings from `diagnose_hanging_queries.py`
4. IRIS error logs showing SQLCODE -400 with malformed `TO_VECTOR()` syntax

**Output**: research.md with consolidated findings (no new research required)

## Phase 1: Design & Contracts

### Data Model (`data-model.md`)
Entities extracted from functional requirements:

1. **OptimizationTrace** (FR-005)
   - original_sql: str
   - optimized_sql: str
   - transformation_time_ms: float
   - validation_status: enum(PASS, FAIL)
   - bracket_detected: bool (FR-008)

2. **BenchmarkResult** (existing, enhanced)
   - query_template_id: str
   - database_method: enum(POSTGRESQL, PGWIRE, DBAPI)
   - execution_time_ms: float
   - row_count: int
   - error_status: Optional[str]
   - optimization_trace: Optional[OptimizationTrace]

3. **IRISErrorContext** (FR-003)
   - sqlcode: int
   - error_message: str
   - problematic_sql: str
   - optimizer_state: dict

4. **DebugLogEntry** (FR-011)
   - timestamp: datetime
   - query_id: str
   - transformation_details: OptimizationTrace
   - execution_phase: enum(CONNECTION, OPTIMIZATION, EXECUTION, FETCH)
   - error_context: Optional[IRISErrorContext]

### API Contracts (`contracts/`)

**Contract 1: Vector Optimizer Bracket Preservation** (FR-001)
```python
# tests/contract/test_vector_optimizer_syntax.py
def test_optimizer_preserves_brackets_in_literals():
    """Vector literals MUST retain brackets after optimization"""
    optimizer = VectorOptimizer()

    # Test pgvector cosine operator
    sql = "SELECT id, embedding <=> '[0.1,0.2,0.3]' AS distance FROM vectors"
    optimized = optimizer.optimize_query(sql)

    # MUST contain TO_VECTOR with brackets
    assert "TO_VECTOR('[0.1,0.2,0.3]', FLOAT)" in optimized
    # MUST NOT have brackets stripped
    assert "TO_VECTOR('0.1,0.2,0.3', FLOAT)" not in optimized
```

**Contract 2: SQL Syntax Validation** (FR-002)
```python
# tests/contract/test_vector_optimizer_validation.py
def test_optimizer_validates_sql_before_iris():
    """Optimized SQL MUST be validated before execution"""
    optimizer = VectorOptimizer()

    sql = "SELECT id, embedding <=> '[0.1,0.1,0.1]' FROM vectors"
    optimized = optimizer.optimize_query(sql)

    # Validation MUST occur
    validation_result = optimizer.validate_sql(optimized)
    assert validation_result.is_valid
    assert validation_result.has_brackets_in_vector_literals
```

**Contract 3: Query Timeout Protection** (FR-004)
```python
# tests/contract/test_benchmark_timeouts.py
def test_query_has_timeout_protection():
    """Queries MUST timeout instead of hanging indefinitely"""
    executor = PGWireExecutor(timeout_seconds=10)

    # Simulate hanging query
    result = executor.execute_with_timeout("SELECT SLEEP(30)")

    # MUST timeout, not hang
    assert result.status == "TIMEOUT"
    assert result.elapsed_time_ms < 11000  # 10s + 1s tolerance
```

### Quickstart Validation (`quickstart.md`)
E2E validation procedure extracted from user scenarios:

1. Fix vector optimizer and verify syntax
2. Run dry-run mode to validate queries
3. Execute 3-way benchmark with debug logging
4. Verify debug output contains optimization traces
5. Confirm no timeouts or IRIS compiler crashes

### Agent Context Update
```bash
.specify/scripts/bash/update-agent-context.sh claude
```

**Output**: data-model.md, contracts/, failing tests, quickstart.md, CLAUDE.md updated

## Phase 2: Task Planning Approach
*This section describes what the /tasks command will do - DO NOT execute during /plan*

**Task Generation Strategy**:
- Load `.specify/templates/tasks-template.md` as base
- Generate tasks from Phase 1 contracts and data model
- Each contract → contract test task [P]
- Core optimizer fix → critical path (non-parallel)
- Debug enhancements → parallel per executor
- Integration tests → depend on core fix

**Ordering Strategy**:
1. Contract tests first (TDD)
2. Core optimizer fix (blocks all vector queries)
3. SQL validation layer (prevents compiler crashes)
4. Timeout protection (prevents hangs)
5. Debug logging enhancements (parallel across executors) [P]
6. Integration tests (validate full pipeline)
7. Quickstart validation (E2E confirmation)

**Estimated Output**: 15-20 numbered tasks in tasks.md

**Task Examples**:
1. [P] Create contract test: Vector optimizer bracket preservation
2. [P] Create contract test: SQL syntax validation
3. [P] Create contract test: Query timeout protection
4. Fix vector optimizer regex to preserve brackets in `TO_VECTOR()`
5. Add SQL validation layer before IRIS execution
6. Implement timeout protection in PGWire executor
7. [P] Add debug logging to pgwire_executor.py
8. [P] Add debug logging to postgres_executor.py
9. [P] Add debug logging to dbapi_executor.py
10. Create integration test: Dry-run mode validation
11. Update quickstart.md validation procedure
12. Run E2E benchmark with debug logging enabled

## Phase 3+: Future Implementation
*These phases are beyond the scope of the /plan command*

**Phase 3**: Task execution (/tasks command creates tasks.md)
**Phase 4**: Implementation (execute tasks.md following TDD principles)
**Phase 5**: Validation (run contract tests, integration tests, quickstart E2E)

## Complexity Tracking
*No constitutional violations detected - section left empty*

## Progress Tracking

**Phase Status**:
- [x] Phase 0: Research complete (/plan command)
- [x] Phase 1: Design complete (/plan command)
- [x] Phase 2: Task planning complete (/plan command - describe approach only)
- [ ] Phase 3: Tasks generated (/tasks command)
- [ ] Phase 4: Implementation complete
- [ ] Phase 5: Validation passed

**Gate Status**:
- [x] Initial Constitution Check: PASS
- [x] Post-Design Constitution Check: PASS
- [x] All NEEDS CLARIFICATION resolved (none existed)
- [x] Complexity deviations documented (none)

**Post-Design Constitution Re-check**: ✅ PASS
- No new violations introduced by design
- All contracts align with test-first development
- Performance measurement requirements preserved
- IRIS integration patterns followed

---
*Based on Constitution v1.2.0 - See `.specify/memory/constitution.md`*

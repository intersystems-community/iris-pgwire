# Tasks: 3-Way Database Performance Benchmark

**Input**: Design documents from `/specs/015-add-3-way/`
**Prerequisites**: plan.md, research.md, data-model.md, contracts/benchmark_api.py, quickstart.md

## Execution Flow (main)
```
1. Load plan.md from feature directory
   → Extract: Python 3.11+, psycopg3, iris module, numpy, tabulate
   → Structure: Single project (benchmarks/ directory)
2. Load design documents:
   → data-model.md: 5 entities (BenchmarkConfiguration, ConnectionConfig, TestQuery, PerformanceResult, BenchmarkReport)
   → contracts/benchmark_api.py: API contracts for all entities
   → quickstart.md: Integration test scenarios
3. Generate tasks by category:
   → Setup: Infrastructure, dependencies, directory structure
   → Tests: Contract tests for all entities
   → Core: Data generators, query templates, benchmark runner
   → Integration: Database connections, warmup, metrics collection
   → Polish: Quickstart validation, documentation
4. Apply task rules:
   → Contract tests [P] (different files)
   → Database method implementations [P] (independent)
   → Sequential for shared utilities
5. Validate completeness:
   → All 5 entities have contract tests ✓
   → All 3 database methods implemented ✓
   → All quickstart scenarios covered ✓
```

## Format: `[ID] [P?] Description`
- **[P]**: Can run in parallel (different files, no dependencies)
- All paths relative to repository root

## Path Conventions
Single project structure:
- `benchmarks/` - New benchmark utilities
- `tests/performance/` - New benchmark tests
- `specs/015-add-3-way/` - Design documentation

---

## Phase 3.1: Infrastructure Setup

### T001: Create benchmark directory structure
**File**: `benchmarks/` (new directory)
**Description**: Create the directory structure per plan.md:
```bash
mkdir -p benchmarks/results/json benchmarks/results/tables benchmarks/test_data
```
**Success Criteria**: Directories exist and are empty

### T002: Start PostgreSQL with pgvector container
**File**: N/A (Docker infrastructure)
**Description**: Start PostgreSQL container per quickstart.md:
```bash
docker run --name postgres-benchmark \
  -e POSTGRES_PASSWORD=postgres \
  -e POSTGRES_DB=benchmark \
  -p 5433:5432 \
  -d pgvector/pgvector:pg16

docker exec postgres-benchmark psql -U postgres -d benchmark \
  -c "CREATE EXTENSION IF NOT EXISTS vector;"
```
**Success Criteria**: Container running, pgvector extension enabled
**Dependencies**: None

### T003: Install Python dependencies
**File**: `pyproject.toml` (update)
**Description**: Add benchmark dependencies using uv:
```bash
uv pip install 'psycopg[binary]' numpy tabulate intersystems-iris-dbapi
```
**Success Criteria**: All packages installed, import tests pass
**Dependencies**: None

---

## Phase 3.2: Contract Tests (TDD) ⚠️ MUST COMPLETE BEFORE 3.3
**CRITICAL: These tests MUST be written and MUST FAIL before ANY implementation**

### T004 [P]: Contract test for BenchmarkConfiguration validation
**File**: `tests/performance/test_benchmark_config_contract.py`
**Description**: Write failing test for BenchmarkConfiguration.validate():
- Test valid configuration passes
- Test invalid vector_dimensions raises error
- Test dataset_size < 100K raises error
- Test dataset_size > 1M raises error
- Test missing connection configs raises error
**Contract Reference**: `specs/015-add-3-way/contracts/benchmark_api.py:BenchmarkConfiguration`
**Success Criteria**: Test file exists, all tests fail with NotImplementedError
**Dependencies**: T003

### T005 [P]: Contract test for PerformanceResult validation
**File**: `tests/performance/test_performance_result_contract.py`
**Description**: Write failing test for PerformanceResult.validate():
- Test negative elapsed_ms raises error
- Test success=False without error_message raises error
- Test negative row_count raises error
**Contract Reference**: `specs/015-add-3-way/contracts/benchmark_api.py:PerformanceResult`
**Success Criteria**: Test file exists, all tests fail with NotImplementedError
**Dependencies**: T003

### T006 [P]: Contract test for BenchmarkReport JSON export
**File**: `tests/performance/test_benchmark_report_contract.py`
**Description**: Write failing test for BenchmarkReport.to_json() and to_table_rows():
- Test JSON structure matches specification
- Test table rows format (5 columns per row)
- Test all three methods present in output
**Contract Reference**: `specs/015-add-3-way/contracts/benchmark_api.py:BenchmarkReport`
**Success Criteria**: Test file exists, all tests fail with NotImplementedError
**Dependencies**: T003

---

## Phase 3.3: Data Layer Implementation (after tests fail)

### T007 [P]: Implement vector data generator
**File**: `benchmarks/test_data/vector_generator.py`
**Description**: Implement reproducible vector generation per research.md:
```python
def generate_test_vectors(count: int, dimensions: int = 1024, seed: int = 42):
    """Generate normalized random vectors"""
    np.random.seed(seed)
    vectors = np.random.uniform(-1.0, 1.0, size=(count, dimensions))
    vectors = vectors / np.linalg.norm(vectors, axis=1, keepdims=True)
    return vectors
```
**Success Criteria**: Function generates reproducible vectors, unit tests pass
**Dependencies**: T003, T004 (test exists)

### T008 [P]: Implement query templates
**File**: `benchmarks/test_data/query_templates.py`
**Description**: Define query templates for three categories per FR-002:
- Simple SELECT queries
- Vector similarity queries (using <-> operator for PostgreSQL, VECTOR_COSINE for IRIS)
- Complex join queries
**Success Criteria**: Templates defined for all three query categories
**Dependencies**: T003

### T009: Implement connection validation
**File**: `benchmarks/validate_connections.py`
**Description**: Implement connection validation per FR-006 and quickstart.md:
- Test IRIS + PGWire (localhost:5432)
- Test PostgreSQL + psycopg3 (localhost:5433)
- Test IRIS + DBAPI (localhost:1972)
- Abort with clear error if any connection fails
**Success Criteria**: Script validates all three connections, exits with error code on failure
**Dependencies**: T003, T008

### T010: Create test data setup script
**File**: `benchmarks/test_data/setup_databases.py`
**Description**: Create identical test data in all three databases per FR-008:
- Generate vectors using vector_generator.py
- Create tables with vector columns
- Insert same data into IRIS (via PGWire and DBAPI) and PostgreSQL
- Create HNSW indexes per Constitution Principle VI
**Success Criteria**: All three databases contain identical test data
**Dependencies**: T007, T008, T009

---

## Phase 3.4: Benchmark Core Implementation

### T011: Implement BenchmarkConfiguration dataclass
**File**: `benchmarks/config.py`
**Description**: Implement BenchmarkConfiguration with validation per data-model.md:
- All fields with defaults (vector_dimensions=1024, dataset_size=100000, etc.)
- validate() method checking all constraints
- Load from YAML file support
**Success Criteria**: T004 contract tests pass
**Dependencies**: T004 (tests written)

### T012: Implement PerformanceResult dataclass
**File**: `benchmarks/config.py` (continue)
**Description**: Implement PerformanceResult with validation:
- All fields per data-model.md
- validate() method per contract
**Success Criteria**: T005 contract tests pass
**Dependencies**: T005 (tests written)

### T013: Implement metrics calculation utilities
**File**: `benchmarks/metrics.py`
**Description**: Implement percentile and QPS calculations per research.md:
```python
def calculate_metrics(timings: List[float]) -> Dict:
    """Calculate P50/P95/P99 latencies and QPS"""
    p50 = np.percentile(timings, 50)
    p95 = np.percentile(timings, 95)
    p99 = np.percentile(timings, 99)
    qps = len(timings) / (sum(timings) / 1000)
    return {"p50_ms": p50, "p95_ms": p95, "p99_ms": p99, "qps": qps}
```
**Success Criteria**: Accurate percentile calculations, unit tests pass
**Dependencies**: T003

### T014: Implement warmup execution
**File**: `benchmarks/runner.py`
**Description**: Implement warmup query execution per FR-009:
- Execute 100 warmup queries before measurements
- Use same query templates as benchmark
- Discard warmup timings
**Success Criteria**: Warmup completes without affecting measurements
**Dependencies**: T008, T009

### T015: Implement timing measurement with perf_counter
**File**: `benchmarks/runner.py` (continue)
**Description**: Implement high-resolution timing per research.md:
```python
import time
start = time.perf_counter()
# Execute query
elapsed = time.perf_counter() - start
```
**Success Criteria**: Nanosecond precision timing, constitutional <5ms overhead validated
**Dependencies**: T003

---

## Phase 3.5: Database Method Implementations (parallel execution)

### T016 [P]: Implement IRIS + PGWire query executor
**File**: `benchmarks/executors/pgwire_executor.py`
**Description**: Implement query execution via psycopg3 to PGWire server:
- Connection to localhost:5432
- Execute simple, vector, and join queries
- Return PerformanceResult objects
**Success Criteria**: Queries execute successfully, results captured
**Dependencies**: T009, T012, T015

### T017 [P]: Implement PostgreSQL + psycopg3 query executor
**File**: `benchmarks/executors/postgres_executor.py`
**Description**: Implement query execution via psycopg3 to PostgreSQL:
- Connection to localhost:5433
- Execute simple, vector (pgvector), and join queries
- Return PerformanceResult objects
**Success Criteria**: Queries execute successfully, results captured
**Dependencies**: T009, T012, T015

### T018 [P]: Implement IRIS + DBAPI query executor
**File**: `benchmarks/executors/dbapi_executor.py`
**Description**: Implement query execution via intersystems-iris-dbapi:
- Connection to localhost:1972
- Execute simple, vector (IRIS VECTOR functions), and join queries
- Return PerformanceResult objects
**Success Criteria**: Queries execute successfully, results captured
**Dependencies**: T009, T012, T015

---

## Phase 3.6: Benchmark Runner Integration

### T019: Implement BenchmarkRunner class
**File**: `benchmarks/runner.py` (continue)
**Description**: Implement main BenchmarkRunner per contracts/benchmark_api.py:
- Initialize with BenchmarkConfiguration
- Validate connections (abort on failure per FR-006)
- Execute warmup queries
- Run benchmark across all three methods
- Collect PerformanceResult instances
- Generate BenchmarkReport
**Success Criteria**: End-to-end benchmark execution works
**Dependencies**: T011, T014, T016, T017, T018

### T020: Implement BenchmarkReport aggregation
**File**: `benchmarks/report.py`
**Description**: Implement BenchmarkReport with aggregation:
- Aggregate PerformanceResult instances into MethodResults
- Calculate metrics per category (simple, vector, join)
- Implement to_json() and to_table_rows() methods
**Success Criteria**: T006 contract tests pass
**Dependencies**: T006 (tests written), T013 (metrics calculation)

---

## Phase 3.7: Output Formatting (FR-010)

### T021 [P]: Implement JSON export
**File**: `benchmarks/output/json_exporter.py`
**Description**: Implement JSON export per FR-010:
- Use BenchmarkReport.to_json()
- Write to benchmarks/results/json/benchmark_TIMESTAMP.json
- Pretty-print with indent=2
**Success Criteria**: JSON files generated, valid JSON schema
**Dependencies**: T020

### T022 [P]: Implement console table export
**File**: `benchmarks/output/table_exporter.py`
**Description**: Implement console table export per FR-010:
- Use BenchmarkReport.to_table_rows()
- Format with tabulate library
- Display to console and save to benchmarks/results/tables/
**Success Criteria**: Tables formatted correctly per specification
**Dependencies**: T020

---

## Phase 3.8: Main Benchmark Script

### T023: Implement 3way_comparison.py main script
**File**: `benchmarks/3way_comparison.py`
**Description**: Implement CLI entry point:
- Parse command-line arguments (--vector-dims, --dataset-size, --iterations)
- Load configuration from YAML if --config provided
- Run BenchmarkRunner
- Export results via JSON and table exporters
- Handle errors per FR-006 (abort on connection failure)
**Success Criteria**: Script runs end-to-end, produces both output formats
**Dependencies**: T019, T021, T022

---

## Phase 3.9: Integration Tests

### T024 [P]: Test end-to-end benchmark with all three methods
**File**: `tests/performance/test_3way_integration.py`
**Description**: Integration test covering quickstart scenario 1:
- Start with small dataset (1000 rows) for fast test
- Run complete benchmark
- Verify all three methods have results
- Verify JSON and table outputs created
**Success Criteria**: Test passes, validates FR-001 (all three methods)
**Dependencies**: T023

### T025 [P]: Test abort-on-failure behavior
**File**: `tests/performance/test_connection_failure.py`
**Description**: Integration test for FR-006:
- Simulate PostgreSQL connection failure (stop container)
- Run benchmark
- Verify benchmark aborts with clear error
- Verify no partial results generated
**Success Criteria**: Test passes, validates FR-006 (abort on failure)
**Dependencies**: T023

### T026 [P]: Test identical data validation
**File**: `tests/performance/test_data_consistency.py`
**Description**: Integration test for FR-008:
- Generate test data
- Verify all three databases have identical vectors
- Run benchmark
- Verify query results consistent across methods
**Success Criteria**: Test passes, validates FR-008 (identical data)
**Dependencies**: T010, T023

### T027 [P]: Test performance metrics accuracy
**File**: `tests/performance/test_metrics_accuracy.py`
**Description**: Unit test for metrics calculation:
- Test percentile calculations match numpy
- Test QPS calculation accuracy
- Test timing precision (nanosecond level)
- Validate constitutional <5ms overhead requirement
**Success Criteria**: Test passes, validates FR-004 (accurate metrics)
**Dependencies**: T013

---

## Phase 3.10: Quickstart Validation

### T028: Execute quickstart.md scenarios
**File**: `specs/015-add-3-way/quickstart.md` (manual execution)
**Description**: Execute all quickstart validation scenarios:
- Acceptance Scenario 1: All three methods configured
- Acceptance Scenario 2: Multiple query types
- Acceptance Scenario 3: Performance metrics present
- Acceptance Scenario 4: Configuration control
- Error handling test: Connection failure abort
**Success Criteria**: All scenarios pass, quickstart.md validated end-to-end
**Dependencies**: T023, T024, T025, T026

---

## Dependencies

```
Setup (T001-T003) → Contract Tests (T004-T006) → Data Layer (T007-T010)
                                                        ↓
                                                   Core Impl (T011-T015)
                                                        ↓
                                        Database Methods (T016-T018) [PARALLEL]
                                                        ↓
                                                   Runner (T019-T020)
                                                        ↓
                                                Output (T021-T022) [PARALLEL]
                                                        ↓
                                                   Main Script (T023)
                                                        ↓
                                           Integration Tests (T024-T027) [PARALLEL]
                                                        ↓
                                                Quickstart (T028)
```

## Parallel Execution Examples

Execute all contract tests in parallel:
```bash
# Run T004, T005, T006 simultaneously
uv run pytest tests/performance/test_benchmark_config_contract.py \
       tests/performance/test_performance_result_contract.py \
       tests/performance/test_benchmark_report_contract.py -n 3
```

Execute all database method implementations in parallel:
```bash
# Work on T016, T017, T018 simultaneously (different files)
# Open three terminal windows or use tmux
```

Execute all integration tests in parallel:
```bash
# Run T024, T025, T026, T027 simultaneously
uv run pytest tests/performance/ -n 4
```

## Task Summary

- **Total Tasks**: 28
- **Parallel Tasks**: 13 (marked [P])
- **Sequential Tasks**: 15
- **Estimated Completion**: 3-5 days (with parallel execution)

## Constitutional Compliance Checks

- ✅ **Principle II (Test-First)**: Contract tests (T004-T006) before implementation
- ✅ **Principle IV (IRIS Integration)**: Uses iris.sql.exec() patterns (T018)
- ✅ **Principle V (Production Readiness)**: Error handling (T009, T023), observability (T021-T022)
- ✅ **Principle VI (Vector Performance)**: Production scale testing (100K-1M rows), HNSW indexes (T010)
- ✅ **Performance Standards**: <5ms translation overhead validated (T027)

---

*Generated from specs/015-add-3-way/ design documents*
*Ready for execution - each task is specific and immediately actionable*

# Tasks: Benchmark Debug Capabilities and Vector Optimizer Fix

**Input**: Design documents from `/specs/016-add-requirements-to/`
**Prerequisites**: plan.md, research.md, data-model.md, contracts/, quickstart.md

## Execution Flow (main)
```
1. Load plan.md from feature directory ✅
   → Tech stack: Python 3.11, psycopg, intersystems-iris-dbapi, numpy
   → Structure: Single project (src/, benchmarks/, tests/)
2. Load optional design documents ✅
   → data-model.md: 4 entities (OptimizationTrace, BenchmarkResult, IRISErrorContext, DebugLogEntry)
   → contracts/: 3 contract specs (vector_optimizer_syntax, sql_validation, query_timeout)
   → research.md: Root cause identified (bracket stripping in optimizer)
3. Generate tasks by category ✅
   → Setup: Verify prerequisites
   → Tests: 3 contract tests + 2 integration tests
   → Core: Optimizer fix, validation layer, timeout protection
   → Integration: Debug logging, error context
   → Polish: E2E validation, quickstart
4. Apply task rules ✅
   → Different files = [P] for parallel
   → Tests before implementation (TDD)
5. Number tasks sequentially (T001-T018) ✅
6. Generate dependency graph ✅
7. Create parallel execution examples ✅
8. Validate task completeness ✅
   → All 3 contracts have tests ✅
   → All 4 entities have implementation tasks ✅
   → Critical fix path identified ✅
9. Return: SUCCESS (18 tasks ready for execution)
```

## Format: `[ID] [P?] Description`
- **[P]**: Can run in parallel (different files, no dependencies)
- Include exact file paths in descriptions

## Phase 3.1: Setup & Verification
- [ ] **T001** Verify IRIS and benchmark containers are running
  - Check `docker ps` for iris-benchmark, pgwire-benchmark, postgres-benchmark
  - Ensure IRIS is ready: `docker exec iris-benchmark /usr/irissys/dev/Cloud/ICM/waitISC.sh`
  - File: N/A (infrastructure verification)

## Phase 3.2: Tests First (TDD) ⚠️ MUST COMPLETE BEFORE 3.3
**CRITICAL: These tests MUST be written and MUST FAIL before ANY implementation**

- [ ] **T002** [P] Contract test: Vector optimizer bracket preservation in `tests/contract/test_vector_optimizer_syntax.py`
  - From contract: `specs/016-add-requirements-to/contracts/vector_optimizer_syntax.md`
  - Test cases: cosine operator, L2 operator, inner product, large vectors (1024D), ORDER BY
  - MUST assert: `TO_VECTOR('[0.1,0.2,0.3]', FLOAT)` preserved (brackets NOT stripped)
  - Expected: FAIL (optimizer currently strips brackets)

- [ ] **T003** [P] Contract test: SQL syntax validation in `tests/contract/test_vector_optimizer_validation.py`
  - From contract: `specs/016-add-requirements-to/contracts/sql_validation.md`
  - Test cases: valid SQL passes, missing brackets fails, malformed TO_VECTOR fails, multiple literals
  - MUST assert: `validate_sql()` method detects bracket absence
  - Expected: FAIL (validate_sql() method doesn't exist yet)

- [ ] **T004** [P] Contract test: Query timeout protection in `tests/contract/test_benchmark_timeouts.py`
  - From contract: `specs/016-add-requirements-to/contracts/query_timeout.md`
  - Test cases: normal query completes, hanging query times out, cleanup releases connection
  - MUST assert: timeout after 10s, no indefinite hangs
  - Expected: FAIL (execute_with_timeout() method doesn't exist yet)

- [ ] **T005** [P] Integration test: Dry-run mode validation in `tests/integration/test_benchmark_debug.py`
  - From quickstart: Step 2 validation
  - Test: Run benchmark with `--dry-run` flag, verify no IRIS execution
  - MUST assert: All queries validated, bracket_detected=True, no database hits
  - Expected: FAIL (dry-run mode doesn't exist yet)

- [ ] **T006** [P] Integration test: Debug logging E2E in `tests/integration/test_benchmark_debug.py`
  - From quickstart: Step 4 validation
  - Test: Run benchmark with `ENABLE_DEBUG_LOGGING=true`, verify JSON output
  - MUST assert: optimization_trace present, transformation_time_ms < 5ms
  - Expected: FAIL (debug logging not implemented yet)

## Phase 3.3: Core Implementation (ONLY after tests are failing)

- [ ] **T007** Fix vector optimizer regex to preserve brackets in `src/iris_pgwire/vector_optimizer.py`
  - **CRITICAL FIX** - Blocks all vector queries
  - Locate operator rewriting regex patterns (lines with `<=>`, `<->`, `<#>`)
  - Change: Ensure brackets `[...]` preserved in TO_VECTOR() calls
  - Before: `TO_VECTOR('0.1,0.2,0.3', FLOAT)` (missing brackets)
  - After: `TO_VECTOR('[0.1,0.2,0.3]', FLOAT)` (brackets preserved)
  - Verify: T002 contract test now PASSES

- [ ] **T008** Add SQL syntax validation method in `src/iris_pgwire/vector_optimizer.py`
  - Add `validate_sql(sql: str) -> ValidationResult` method
  - Implement bracket detection: Scan for `TO_VECTOR('...')` and check for `[...]` inside
  - Implement function signature check: Validate `TO_VECTOR(literal, FLOAT)` format
  - Return ValidationResult with: is_valid, has_brackets_in_vector_literals, error_message
  - Verify: T003 contract test now PASSES

- [ ] **T009** [P] Add OptimizationTrace data class in `src/iris_pgwire/vector_optimizer.py`
  - From data-model.md: OptimizationTrace entity
  - Fields: original_sql, optimized_sql, transformation_time_ms, validation_status, bracket_detected
  - Return OptimizationTrace from `optimize_query()` method
  - Ensure transformation_time_ms calculation added to optimizer

- [ ] **T010** [P] Add IRISErrorContext data class in `src/iris_pgwire/iris_executor.py`
  - From data-model.md: IRISErrorContext entity
  - Fields: sqlcode, error_message, problematic_sql, optimizer_state
  - Capture in exception handlers: Wrap `iris.Error` with IRISErrorContext
  - Include full query context when SQLCODE -400 occurs

- [ ] **T011** Implement query timeout protection in `benchmarks/executors/pgwire_executor.py`
  - Add `execute_with_timeout(sql: str, timeout_seconds: int = 10)` method
  - Use signal-based timeout (Unix) or threading-based (cross-platform)
  - On timeout: Cancel query, release connection, return TimeoutResult
  - Verify: T004 contract test now PASSES

- [ ] **T012** Add debug configuration flags in `benchmarks/config.py`
  - Add ENABLE_DEBUG_LOGGING environment variable support
  - Add dry-run mode flag: `--dry-run` CLI argument
  - Add debug_config dataclass: enable_logging, dry_run_mode, timeout_seconds
  - Update BenchmarkResult to include optimization_trace field

## Phase 3.4: Integration & Debug Logging

- [ ] **T013** [P] Add debug logging to PGWire executor in `benchmarks/executors/pgwire_executor.py`
  - From FR-005, FR-006: Log original SQL, optimized SQL, transformation time
  - From FR-011: Structured logging with timestamp, query_id, execution phase
  - Create DebugLogEntry for each execution: CONNECTION → OPTIMIZATION → EXECUTION → FETCH
  - Include optimization_trace in BenchmarkResult output

- [ ] **T014** [P] Add debug logging to Postgres executor in `benchmarks/executors/postgres_executor.py`
  - Consistent error handling with pgwire_executor
  - Log execution phases (no optimization trace needed for PostgreSQL)
  - Capture and format errors for comparison with IRIS errors

- [ ] **T015** [P] Add debug logging to DBAPI executor in `benchmarks/executors/dbapi_executor.py`
  - Consistent error handling with pgwire_executor
  - Log execution phases (no optimization trace needed for DBAPI)
  - Capture IRIS errors with SQLCODE context

- [ ] **T016** Implement dry-run mode in `benchmarks/3way_comparison.py`
  - Add `--dry-run` CLI flag
  - When enabled: Validate queries without database execution
  - Call `validate_sql()` on all queries, report bracket_detected status
  - Verify: T005 integration test now PASSES

- [ ] **T017** Update JSON/table exporters with debug metrics in `benchmarks/output/`
  - Modify `json_exporter.py`: Include optimization_trace in JSON output
  - Modify `table_exporter.py`: Show P50/P95/P99 latencies, success/failure counts
  - From FR-017: Display latency percentiles for each query template
  - Verify: T006 integration test now PASSES

## Phase 3.5: Polish & Validation

- [ ] **T018** Run E2E validation via quickstart.md
  - Execute all 6 steps from `specs/016-add-requirements-to/quickstart.md`
  - Step 1: Contract tests pass ✅
  - Step 2: Dry-run mode validates queries ✅
  - Step 3: 3-way benchmark completes without timeouts ✅
  - Step 4: Debug output contains optimization traces ✅
  - Step 5: No indefinite hangs (timeout protection works) ✅
  - Step 6: P50/P95/P99 metrics displayed ✅
  - Expected: All acceptance criteria PASS, no IRIS SQLCODE -400 errors

## Dependencies

**Critical Path**:
```
T001 (setup)
  ↓
T002, T003, T004 (contract tests) [P]
  ↓
T007 (optimizer fix) ← BLOCKS ALL VECTOR QUERIES
  ↓
T008 (SQL validation)
  ↓
T009, T010 (data classes) [P]
  ↓
T011 (timeout protection)
  ↓
T012 (config flags)
  ↓
T013, T014, T015 (debug logging) [P]
  ↓
T016 (dry-run mode)
  ↓
T017 (output formatting)
  ↓
T018 (E2E validation)
```

**Parallel Execution Points**:
- T002-T004: Contract tests (different files)
- T005-T006: Integration tests (same file, but independent test functions)
- T009-T010: Data classes (different files)
- T013-T015: Executor logging (different files)

## Parallel Example

**Launch contract tests together** (T002-T004):
```bash
# All 3 contract tests can run in parallel
pytest tests/contract/test_vector_optimizer_syntax.py \
       tests/contract/test_vector_optimizer_validation.py \
       tests/contract/test_benchmark_timeouts.py \
       -v
```

**Launch executor debug logging together** (T013-T015):
```python
# Task agent commands (if using Task tool):
Task: "Add debug logging to PGWire executor in benchmarks/executors/pgwire_executor.py"
Task: "Add debug logging to Postgres executor in benchmarks/executors/postgres_executor.py"
Task: "Add debug logging to DBAPI executor in benchmarks/executors/dbapi_executor.py"
```

## Notes

- **[P] tasks** = different files, no dependencies
- **T007 is CRITICAL** - Optimizer fix unblocks all vector queries
- Verify tests FAIL before implementing (TDD principle)
- Commit after each task with descriptive message
- Constitutional requirement: transformation_time_ms MUST be <5ms

## Task Generation Rules Applied

1. **From Contracts**:
   - `vector_optimizer_syntax.md` → T002 (contract test)
   - `sql_validation.md` → T003 (contract test)
   - `query_timeout.md` → T004 (contract test)

2. **From Data Model**:
   - OptimizationTrace entity → T009 (data class)
   - IRISErrorContext entity → T010 (data class)
   - BenchmarkResult enhancement → T012 (config)
   - DebugLogEntry → T013-T015 (logging)

3. **From Functional Requirements**:
   - FR-001 (bracket preservation) → T007 (optimizer fix)
   - FR-002 (SQL validation) → T008 (validation layer)
   - FR-004 (timeout protection) → T011 (timeout)
   - FR-009 (dry-run mode) → T016 (dry-run)
   - FR-005, FR-006, FR-011 (debug logging) → T013-T015
   - FR-017 (P50/P95/P99 metrics) → T017 (exporters)

4. **From Quickstart**:
   - 6-step validation procedure → T018 (E2E validation)

## Validation Checklist
*GATE: Verified before task generation completion*

- [x] All contracts have corresponding tests (T002-T004)
- [x] All entities have implementation tasks (T009-T010, T012-T015)
- [x] All tests come before implementation (T002-T006 before T007-T017)
- [x] Parallel tasks truly independent (different files, verified)
- [x] Each task specifies exact file path
- [x] No task modifies same file as another [P] task

---
**Total Tasks**: 18
**Estimated Completion**: 2-3 days (with TDD approach)
**Critical Path**: T001 → T002-T004 → T007 → T008 → ... → T018

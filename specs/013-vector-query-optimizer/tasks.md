# Tasks: Vector Query Optimizer for HNSW Compatibility

**Feature**: 013-vector-query-optimizer
**Branch**: `013-vector-query-optimizer`
**Input**: Design documents from `/Users/tdyar/ws/iris-pgwire/specs/013-vector-query-optimizer/`
**Prerequisites**: plan.md ✅, research.md ✅, data-model.md ✅, quickstart.md ✅

## Execution Flow (main)
```
1. Load plan.md from feature directory ✅
   → Tech stack: Python 3.11+, asyncio, regex, base64, struct, pytest
   → Structure: Single project (src/iris_pgwire/, tests/)
2. Load optional design documents ✅
   → data-model.md: 5 entities (Vector Query, Vector Parameter, Vector Literal, Transformation Context, Vector Format)
   → research.md: JSON array literal format, regex pattern, base64 conversion, E2E debugging strategy
   → quickstart.md: 5 acceptance scenarios, performance validation steps
3. Generate tasks by category ✅
   → Setup: No new dependencies (existing Python project)
   → Tests: Contract tests for optimizer functions, E2E tests with real clients, performance tests
   → Core: Fix multi-parameter handling, enhance logging, integration debugging
   → Integration: Performance monitoring, constitutional compliance tracking
   → Polish: Documentation, benchmarking, quickstart validation
4. Apply task rules ✅
   → Different files = mark [P] for parallel
   → Same file (vector_optimizer.py) = sequential
   → Tests before implementation (TDD)
5. Number tasks sequentially (T001-T028) ✅
6. Generate dependency graph ✅
7. Create parallel execution examples ✅
8. Validate task completeness ✅
   → All contracts have tests ✅
   → All entities validated ✅
   → E2E scenarios implemented ✅
9. Return: SUCCESS (tasks ready for execution) ✅
```

## Format: `[ID] [P?] Description`
- **[P]**: Can run in parallel (different files, no dependencies)
- Include exact file paths in descriptions

## Path Conventions
**Project Type**: Single project
- **Source**: `/Users/tdyar/ws/iris-pgwire/src/iris_pgwire/`
- **Tests**: `/Users/tdyar/ws/iris-pgwire/tests/`
- **Benchmarks**: `/Users/tdyar/ws/iris-pgwire/benchmarks/`
- **Specs**: `/Users/tdyar/ws/iris-pgwire/specs/013-vector-query-optimizer/`

## Phase 3.1: Setup & Validation

**Prerequisites**: Existing vector_optimizer.py and iris_executor.py integration already implemented

- [ ] **T001** [P] Verify IRIS Build 127 EHAT with vector licensing
  - **File**: Environment verification
  - **Action**: Run `uv run python -c "import iris; ..."` to test vector functions
  - **Success Criteria**: Vector TO_VECTOR() and VECTOR_COSINE() functions work
  - **Dependencies**: None (environment check)

- [ ] **T002** [P] Verify HNSW test data and indexes exist
  - **File**: `/Users/tdyar/ws/iris-pgwire/create_test_vectors.py` (existing)
  - **Action**: Check test_1024 table has 1000+ vectors and HNSW index
  - **Success Criteria**: `SELECT COUNT(*) FROM test_1024` returns 1000+, HNSW index exists
  - **Dependencies**: None (data verification)

- [ ] **T003** [P] Run DBAPI baseline benchmark
  - **File**: `/Users/tdyar/ws/iris-pgwire/benchmark_iris_dbapi.py` (existing)
  - **Action**: Execute benchmark to confirm 335+ qps baseline
  - **Success Criteria**: Output shows 335+ qps, <50ms P95 latency
  - **Dependencies**: T001, T002

## Phase 3.2: Tests First (TDD) ⚠️ MUST COMPLETE BEFORE 3.3

**CRITICAL: These tests MUST be written and MUST FAIL before ANY implementation fixes**

### Contract Tests (Internal API)

- [ ] **T004** [P] Contract test optimize_vector_query() with base64 input
  - **File**: `/Users/tdyar/ws/iris-pgwire/tests/contract/test_optimize_vector_query_contract.py`
  - **Action**: Test base64 vector transformation to JSON array literal
  - **Test Case**: `test_base64_vector_transformation()`
  - **Expected**: FAIL initially (multi-param handling broken)
  - **Dependencies**: None (pure unit test)

- [ ] **T005** [P] Contract test optimize_vector_query() with multi-parameters
  - **File**: `/Users/tdyar/ws/iris-pgwire/tests/contract/test_optimize_vector_query_contract.py`
  - **Action**: Test `SELECT TOP %s ... ORDER BY ... LIMIT %s` preserves non-vector params
  - **Test Case**: `test_multi_parameter_preservation()`
  - **Expected**: FAIL initially (parameter index calculation incorrect)
  - **Dependencies**: None (pure unit test)

- [ ] **T006** [P] Contract test optimize_vector_query() graceful degradation
  - **File**: `/Users/tdyar/ws/iris-pgwire/tests/contract/test_optimize_vector_query_contract.py`
  - **Action**: Test unknown format passes through unchanged
  - **Test Case**: `test_unknown_format_graceful_degradation()`
  - **Expected**: MAY PASS (graceful degradation already implemented)
  - **Dependencies**: None (pure unit test)

- [ ] **T007** [P] Contract test optimize_vector_query() performance SLA
  - **File**: `/Users/tdyar/ws/iris-pgwire/tests/contract/test_optimize_vector_query_contract.py`
  - **Action**: Test 4096-dim vector completes within 10ms budget
  - **Test Case**: `test_performance_sla_compliance()`
  - **Expected**: FAIL if >10ms (performance baseline needed)
  - **Dependencies**: None (pure unit test)

- [ ] **T008** [P] Contract test _convert_vector_to_literal() for all formats
  - **File**: `/Users/tdyar/ws/iris-pgwire/tests/contract/test_convert_vector_to_literal_contract.py`
  - **Action**: Test base64, JSON array, comma-delimited format conversion
  - **Test Cases**: `test_base64_conversion()`, `test_json_array_passthrough()`, `test_comma_delimited_wrapping()`
  - **Expected**: MAY PASS (conversion logic already implemented)
  - **Dependencies**: None (pure unit test)

### Integration Tests (E2E with Real Clients)

- [ ] **T009** [P] E2E test base64 vector query through PGWire
  - **File**: `/Users/tdyar/ws/iris-pgwire/tests/integration/test_vector_optimizer_e2e.py`
  - **Action**: Test psycopg2 client with base64 vector executes with HNSW optimization
  - **Test Case**: `test_base64_vector_e2e()` (from quickstart.md Scenario 1)
  - **Expected**: FAIL currently (timeout, E2E integration issue)
  - **Dependencies**: T001, T002 (environment + data)

- [ ] **T010** [P] E2E test JSON array vector query through PGWire
  - **File**: `/Users/tdyar/ws/iris-pgwire/tests/integration/test_vector_optimizer_e2e.py`
  - **Action**: Test JSON array format with DP-444330 optimization
  - **Test Case**: `test_json_array_vector_e2e()` (from quickstart.md Scenario 2)
  - **Expected**: FAIL currently (same E2E integration issue)
  - **Dependencies**: T001, T002

- [ ] **T011** [P] E2E test multi-parameter query through PGWire
  - **File**: `/Users/tdyar/ws/iris-pgwire/tests/integration/test_vector_optimizer_e2e.py`
  - **Action**: Test `SELECT TOP %s ... ORDER BY ... LIMIT %s` preserves params
  - **Test Case**: `test_multi_parameter_e2e()`
  - **Expected**: FAIL (multi-param handling + E2E issue)
  - **Dependencies**: T001, T002

- [ ] **T012** [P] E2E test non-vector query pass-through
  - **File**: `/Users/tdyar/ws/iris-pgwire/tests/integration/test_vector_optimizer_e2e.py`
  - **Action**: Test queries without ORDER BY or TO_VECTOR are unchanged
  - **Test Case**: `test_non_vector_query_passthrough_e2e()`
  - **Expected**: PASS (no optimization needed)
  - **Dependencies**: T001, T002

### Performance Tests

- [ ] **T013** [P] Performance test transformation overhead
  - **File**: `/Users/tdyar/ws/iris-pgwire/tests/performance/test_optimizer_performance.py`
  - **Action**: Measure transformation time for 128, 384, 1024, 1536, 4096-dim vectors
  - **Test Case**: `test_transformation_overhead_by_dimension()`
  - **Success Criteria**: 128-1024 dims <5ms, 1536 dims <10ms
  - **Dependencies**: None (pure performance test)

- [ ] **T014** [P] Performance test concurrent throughput
  - **File**: `/Users/tdyar/ws/iris-pgwire/tests/performance/test_optimizer_performance.py`
  - **Action**: Test 16 concurrent clients achieve 335+ qps aggregate
  - **Test Case**: `test_concurrent_throughput()`
  - **Success Criteria**: QPS ≥ 335, P95 latency <50ms
  - **Dependencies**: T001, T002 (requires real IRIS + PGWire server)

## Phase 3.3: Core Implementation (ONLY after tests are failing)

**Prerequisites**: T004-T014 tests written and failing

### Bug Fixes & Enhancements

- [ ] **T015** Fix multi-parameter index calculation in vector_optimizer.py
  - **File**: `/Users/tdyar/ws/iris-pgwire/src/iris_pgwire/vector_optimizer.py:84`
  - **Action**: Fix parameter index calculation for queries with multiple placeholders
  - **Current Issue**: `param_index = sql[:match.start()].count('?') + sql[:match.start()].count('%s')`
  - **Fix**: Account for params_used list during reverse iteration
  - **Success Criteria**: T005 (multi-parameter contract test) passes
  - **Dependencies**: T005 (test must be failing first)

- [ ] **T016** Enhance logging in vector_optimizer.py
  - **File**: `/Users/tdyar/ws/iris-pgwire/src/iris_pgwire/vector_optimizer.py:66-128`
  - **Action**: Add detailed logging for transformation steps
  - **Logging Points**:
    - Entry: SQL preview, param count
    - Detection: Pattern matches found, parameter formats detected
    - Transformation: Vector converted, literal substituted
    - Exit: SQL changed flag, params remaining count
  - **Success Criteria**: Debug logs show transformation pipeline clearly
  - **Dependencies**: None (logging enhancement)

- [ ] **T017** Add comprehensive error handling for edge cases
  - **File**: `/Users/tdyar/ws/iris-pgwire/src/iris_pgwire/vector_optimizer.py:132-181`
  - **Action**: Enhance _convert_vector_to_literal() error handling
  - **Edge Cases**:
    - Invalid base64 padding
    - Binary decode failures (corrupted data)
    - Malformed JSON arrays
    - Float parsing errors
  - **Success Criteria**: T006 (graceful degradation test) passes, no exceptions thrown
  - **Dependencies**: T006

### Integration & Debugging

- [ ] **T018** Add extensive logging to iris_executor.py integration point
  - **File**: `/Users/tdyar/ws/iris-pgwire/src/iris_pgwire/iris_executor.py:273-280`
  - **Action**: Log optimizer invocation, optimized SQL, and final IRIS query
  - **Logging Points**:
    - Before optimizer: Original SQL preview, param count
    - After optimizer: Optimized SQL preview, transformation success/failure
    - Before IRIS: Final SQL sent to IRIS, final param count
  - **Success Criteria**: Logs show complete query transformation pipeline
  - **Dependencies**: None (logging enhancement)

- [ ] **T019** Debug E2E integration - trace query path from PGWire to IRIS
  - **File**: Multiple (protocol.py, iris_executor.py, vector_optimizer.py)
  - **Action**: Enable DEBUG logging and trace query execution path
  - **Debug Steps**:
    1. Run E2E test with DEBUG logging enabled
    2. Grep logs for "Vector optimizer" entries
    3. Verify optimized SQL reaches IRIS unchanged
    4. Check if downstream code re-parameterizes
  - **Success Criteria**: Identify exact point where optimization breaks
  - **Dependencies**: T016, T018 (logging enhancements must be in place)

- [ ] **T020** Fix E2E integration issue based on debugging findings
  - **File**: TBD (depends on T019 findings)
  - **Action**: Fix root cause of E2E timeout (likely parameter re-binding)
  - **Possible Fixes**:
    - Prevent re-parameterization after optimization
    - Ensure optimized SQL bypasses parameter binding logic
    - Fix prepared statement handling for optimized queries
  - **Success Criteria**: T009, T010, T011 (E2E tests) pass with <50ms latency
  - **Dependencies**: T019 (root cause analysis must be complete)

## Phase 3.4: Integration & Monitoring

**Prerequisites**: Core implementation (T015-T020) complete, E2E tests passing

- [ ] **T021** [P] Integrate performance monitoring for constitutional compliance
  - **File**: `/Users/tdyar/ws/iris-pgwire/src/iris_pgwire/vector_optimizer.py:184-207`
  - **Action**: Create TransformationContext metrics and integrate with performance monitor
  - **Metrics**: timestamp, duration_ms, sla_compliant, budget_compliant, success
  - **Success Criteria**: Metrics logged for every transformation
  - **Dependencies**: None (can be parallel with fixes)

- [ ] **T022** [P] Add constitutional SLA violation tracking
  - **File**: `/Users/tdyar/ws/iris-pgwire/src/iris_pgwire/performance_monitor.py` (new or existing)
  - **Action**: Track 5ms SLA violations and calculate violation rate
  - **Monitoring**:
    - Log warning if transformation >5ms
    - Log error if transformation >10ms
    - Calculate violation rate (target: <5%)
  - **Success Criteria**: SLA metrics available in performance monitor
  - **Dependencies**: T021 (metrics infrastructure)

- [ ] **T023** Create vector format detection and conversion metrics
  - **File**: `/Users/tdyar/ws/iris-pgwire/src/iris_pgwire/vector_optimizer.py:132-181`
  - **Action**: Track format distribution and conversion success rates
  - **Metrics**:
    - Format frequency (base64, JSON array, comma-delimited, unknown)
    - Conversion success rate per format
    - Average conversion time per format
  - **Success Criteria**: Format metrics logged for analysis
  - **Dependencies**: T021

## Phase 3.5: Validation & Polish

**Prerequisites**: All implementation complete, E2E tests passing

- [ ] **T024** [P] Run quickstart validation (all 5 acceptance criteria)
  - **File**: `/Users/tdyar/ws/iris-pgwire/specs/013-vector-query-optimizer/quickstart.md`
  - **Action**: Execute all quickstart scenarios step-by-step
  - **Validation Steps**:
    1. Verify environment (T001-T003)
    2. Test optimizer standalone (T004-T008)
    3. Test E2E PGWire (T009-T012)
    4. Performance benchmark (T013-T014)
    5. Acceptance criteria (5 scenarios from quickstart.md)
  - **Success Criteria**: All 5 acceptance criteria pass
  - **Dependencies**: T001-T020 (everything implemented)

- [ ] **T025** [P] Run full performance benchmark vs DBAPI baseline
  - **File**: `/Users/tdyar/ws/iris-pgwire/benchmarks/benchmark_vector_optimizer.py` (new)
  - **Action**: Compare PGWire performance to DBAPI baseline (356.5 qps)
  - **Benchmark**: 50 queries, measure throughput and latency
  - **Success Criteria**: PGWire achieves 335+ qps (95% of DBAPI)
  - **Dependencies**: T020 (E2E integration working)

- [ ] **T026** [P] Profile transformation overhead and identify bottlenecks
  - **File**: `/Users/tdyar/ws/iris-pgwire/benchmarks/profile_optimizer.py` (new)
  - **Action**: Use cProfile to identify transformation bottlenecks
  - **Profile Targets**:
    - Regex pattern matching
    - Base64 decoding
    - JSON array string construction
  - **Success Criteria**: Bottleneck analysis documented, optimization opportunities identified
  - **Dependencies**: T020 (implementation complete)

- [ ] **T027** [P] Update CLAUDE.md with vector optimizer patterns
  - **File**: `/Users/tdyar/ws/iris-pgwire/CLAUDE.md`
  - **Action**: Document vector optimizer design patterns and lessons learned
  - **Content**:
    - Regex pattern for TO_VECTOR detection
    - Vector format conversion approaches
    - E2E integration debugging strategy
    - Performance optimization techniques
  - **Success Criteria**: CLAUDE.md updated with practical guidance
  - **Dependencies**: T024, T025, T026 (validation complete)

- [ ] **T028** Final constitutional compliance review
  - **File**: `/Users/tdyar/ws/iris-pgwire/specs/013-vector-query-optimizer/plan.md`
  - **Action**: Verify all constitutional principles are met
  - **Checklist**:
    - ✅ Protocol Fidelity: No protocol changes (transformation layer)
    - ✅ Test-First Development: E2E tests with real clients pass
    - ✅ Phased Implementation: Integrates with P5 (vectors)
    - ✅ IRIS Integration: Uses existing iris_executor pattern
    - ✅ Production Readiness: Logging, metrics, error handling complete
    - ✅ Performance Standards: <5ms SLA met, <5% violation rate
  - **Success Criteria**: All constitutional gates pass
  - **Dependencies**: T001-T027 (everything complete)

## Dependencies

### Critical Path
```
Setup (T001-T003) → Tests (T004-T014) → Implementation (T015-T020) → Validation (T024-T028)
```

### Detailed Dependencies

**Setup Phase**:
- T001, T002, T003 can run in parallel [P]

**Test Phase** (all can run in parallel after setup):
- T004-T008: Contract tests [P] (depend on T001)
- T009-T012: E2E tests [P] (depend on T001, T002)
- T013-T014: Performance tests [P] (depend on T001, T002 for E2E variant)

**Implementation Phase** (sequential, fixes must be tested):
- T015: Multi-parameter fix → blocks T005 passing
- T016: Logging enhancement → enables T019 debugging
- T017: Error handling → blocks T006 passing
- T018: Executor logging → enables T019 debugging
- T019: E2E debugging → required for T020
- T020: E2E fix → blocks T009-T011 passing

**Integration Phase** (can run in parallel):
- T021: Performance monitoring [P]
- T022: SLA tracking [P] (depends on T021)
- T023: Format metrics [P] (depends on T021)

**Validation Phase** (can run in parallel after implementation):
- T024: Quickstart validation [P] (depends on T001-T020)
- T025: Performance benchmark [P] (depends on T020)
- T026: Profiling [P] (depends on T020)
- T027: Documentation [P] (depends on T024-T026)
- T028: Final review (depends on T001-T027)

## Parallel Execution Examples

### Phase 3.1: Setup (All Parallel)
```bash
# Launch all setup tasks together
Task: "Verify IRIS Build 127 EHAT with vector licensing"
Task: "Verify HNSW test data and indexes exist"
Task: "Run DBAPI baseline benchmark"
```

### Phase 3.2: Contract Tests (Parallel Group 1)
```bash
# Launch all contract tests together
Task: "Contract test optimize_vector_query() with base64 input in tests/contract/test_optimize_vector_query_contract.py"
Task: "Contract test optimize_vector_query() with multi-parameters in tests/contract/test_optimize_vector_query_contract.py"
Task: "Contract test optimize_vector_query() graceful degradation in tests/contract/test_optimize_vector_query_contract.py"
Task: "Contract test optimize_vector_query() performance SLA in tests/contract/test_optimize_vector_query_contract.py"
Task: "Contract test _convert_vector_to_literal() for all formats in tests/contract/test_convert_vector_to_literal_contract.py"
```

### Phase 3.2: E2E Tests (Parallel Group 2)
```bash
# Launch all E2E tests together (expected to fail initially)
Task: "E2E test base64 vector query through PGWire in tests/integration/test_vector_optimizer_e2e.py"
Task: "E2E test JSON array vector query through PGWire in tests/integration/test_vector_optimizer_e2e.py"
Task: "E2E test multi-parameter query through PGWire in tests/integration/test_vector_optimizer_e2e.py"
Task: "E2E test non-vector query pass-through in tests/integration/test_vector_optimizer_e2e.py"
```

### Phase 3.2: Performance Tests (Parallel Group 3)
```bash
# Launch performance tests together
Task: "Performance test transformation overhead in tests/performance/test_optimizer_performance.py"
Task: "Performance test concurrent throughput in tests/performance/test_optimizer_performance.py"
```

### Phase 3.4: Integration Monitoring (Parallel)
```bash
# Launch monitoring tasks together
Task: "Integrate performance monitoring for constitutional compliance in src/iris_pgwire/vector_optimizer.py"
Task: "Add constitutional SLA violation tracking in src/iris_pgwire/performance_monitor.py"
Task: "Create vector format detection and conversion metrics in src/iris_pgwire/vector_optimizer.py"
```

### Phase 3.5: Validation (Parallel)
```bash
# Launch validation tasks together
Task: "Run quickstart validation (all 5 acceptance criteria)"
Task: "Run full performance benchmark vs DBAPI baseline in benchmarks/benchmark_vector_optimizer.py"
Task: "Profile transformation overhead in benchmarks/profile_optimizer.py"
Task: "Update CLAUDE.md with vector optimizer patterns"
```

## Notes

### TDD Enforcement
- **CRITICAL**: T004-T014 (tests) MUST be written and MUST be failing before T015-T020 (implementation)
- Verify tests fail with expected failures (not syntax errors)
- Tests should assert on specific behavior from spec/research

### Parallel Execution Rules
- **[P] tasks**: Different files, no shared state, can run concurrently
- **Sequential tasks**: Same file (e.g., vector_optimizer.py), must run in order
- **Test dependencies**: All tests can run in parallel, but implementation must wait for failing tests

### Git Workflow
- Commit after each task completion
- Use feature branch: `013-vector-query-optimizer`
- Create PR after T028 (final review passes)

### Performance Targets (from research.md)
- **Transformation overhead**: <5ms SLA (constitutional), <10ms budget (practical)
- **E2E throughput**: 335+ qps (95% of DBAPI 356.5 qps baseline)
- **E2E latency**: <50ms P95
- **SLA violation rate**: <5% of queries

### Common Pitfalls to Avoid
1. **Implementing before tests fail**: Violates TDD, leads to incomplete coverage
2. **Skipping E2E debugging (T019)**: Root cause analysis required before fixing (T020)
3. **Ignoring performance monitoring**: Constitutional compliance tracking required
4. **Missing logging enhancements**: Debugging impossible without detailed logs (T016, T018)
5. **Assuming quickstart passes**: Must validate all 5 acceptance criteria (T024)

## Task Generation Rules Applied

1. ✅ **Different files = [P]**: Contract tests (different test files) marked parallel
2. ✅ **Same file = sequential**: vector_optimizer.py fixes (T015, T016, T017) are sequential
3. ✅ **Tests before implementation**: T004-T014 before T015-T020
4. ✅ **Models before services**: Data model already defined (research.md)
5. ✅ **Core before integration**: T015-T020 before T021-T023
6. ✅ **Everything before polish**: T001-T023 before T024-T028

## Success Criteria Summary

**Feature is COMPLETE when**:
1. ✅ All tests (T004-T014) pass
2. ✅ E2E tests show <50ms latency (T009-T011)
3. ✅ Performance benchmark achieves 335+ qps (T025)
4. ✅ Transformation overhead <10ms for typical vectors (T013)
5. ✅ SLA violation rate <5% (T022)
6. ✅ All 5 quickstart acceptance criteria pass (T024)
7. ✅ Constitutional compliance review passes (T028)

---

**Tasks Generated**: 28 tasks across 5 phases
**Estimated Duration**: 5-9 hours (per research.md)
**TDD Tasks**: 11 test tasks (T004-T014)
**Implementation Tasks**: 6 core tasks (T015-T020)
**Integration Tasks**: 3 monitoring tasks (T021-T023)
**Validation Tasks**: 5 polish tasks (T024-T028)
**Parallel Groups**: 6 parallel execution groups identified

**Next Step**: Execute T001 (environment verification) to begin implementation

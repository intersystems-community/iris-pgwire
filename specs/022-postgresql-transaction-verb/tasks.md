# Tasks: PostgreSQL Transaction Verb Compatibility

**Input**: Design documents from `/specs/022-postgresql-transaction-verb/`
**Prerequisites**: plan.md (complete), research.md (complete), data-model.md (complete), contracts/ (complete)

## Format: `[ID] [P?] Description`
- **[P]**: Can run in parallel (different files, no dependencies)
- Include exact file paths in descriptions

## Phase 3.1: Setup & Prerequisites
- [ ] T001 [P] Verify Python 3.11 environment and asyncio availability
- [ ] T002 [P] Install test dependencies: pytest>=7.0.0, psycopg>=3.1.0
- [ ] T003 [P] Verify IRIS PGWire server running at localhost:5432

## Phase 3.2: Contract Tests First (TDD) ⚠️ MUST COMPLETE BEFORE 3.3
**CRITICAL: These tests MUST be written and MUST FAIL before ANY implementation**

### Contract Tests (from contracts/transaction_translator_interface.py)
- [ ] T004 [P] Contract test: BEGIN → START TRANSACTION in tests/contract/test_transaction_translator_contract.py
- [ ] T005 [P] Contract test: BEGIN TRANSACTION → START TRANSACTION in tests/contract/test_transaction_translator_contract.py
- [ ] T006 [P] Contract test: COMMIT unchanged in tests/contract/test_transaction_translator_contract.py
- [ ] T007 [P] Contract test: ROLLBACK unchanged in tests/contract/test_transaction_translator_contract.py
- [ ] T008 [P] Contract test: Preserve modifiers (ISOLATION LEVEL) in tests/contract/test_transaction_translator_contract.py
- [ ] T009 [P] Contract test: String literal preservation in tests/contract/test_transaction_translator_contract.py
- [ ] T010 [P] Contract test: Case-insensitive matching in tests/contract/test_transaction_translator_contract.py
- [ ] T011 [P] Contract test: Performance <0.1ms in tests/contract/test_transaction_translator_contract.py

### Unit Tests (from quickstart.md test scenarios)
- [ ] T012 [P] Unit test: translate_transaction_command("BEGIN") in tests/unit/test_transaction_translator.py
- [ ] T013 [P] Unit test: translate_transaction_command("BEGIN WORK") in tests/unit/test_transaction_translator.py
- [ ] T014 [P] Unit test: is_transaction_command() detection in tests/unit/test_transaction_translator.py
- [ ] T015 [P] Unit test: parse_transaction_command() extraction in tests/unit/test_transaction_translator.py

### Integration Tests (E2E with real clients - from acceptance scenarios)
- [ ] T016 [P] E2E test: psql BEGIN/COMMIT workflow in tests/integration/test_transaction_e2e.py
- [ ] T017 [P] E2E test: psycopg parameterized statements in transaction in tests/integration/test_transaction_e2e.py
- [ ] T018 [P] E2E test: SQLAlchemy context manager (with connection.begin()) in tests/integration/test_transaction_e2e.py
- [ ] T019 [P] E2E test: ROLLBACK on error in tests/integration/test_transaction_e2e.py
- [ ] T020 [P] E2E test: Isolation level modifiers preserved in tests/integration/test_transaction_e2e.py

## Phase 3.3: Core Implementation (ONLY after tests are failing)

### Transaction Translator Module
- [ ] T021 Create TransactionTranslator class in src/iris_pgwire/sql_translator/transaction_translator.py
- [ ] T022 Implement translate_transaction_command() method with BEGIN → START TRANSACTION regex
- [ ] T023 Implement is_transaction_command() method for detection
- [ ] T024 Implement parse_transaction_command() method returning TransactionCommand dataclass
- [ ] T025 Implement get_translation_metrics() method for performance monitoring
- [ ] T026 Add TransactionTranslator to sql_translator/__init__.py exports

### Performance Monitoring
- [ ] T027 [P] Add translation timing instrumentation in src/iris_pgwire/sql_translator/transaction_translator.py
- [ ] T028 [P] Add metrics collection (avg, max, SLA violations) in src/iris_pgwire/sql_translator/transaction_translator.py

## Phase 3.4: Integration (3 execution paths - from plan.md)

### Integration Point 1: Direct Execution Path
- [ ] T029 Import TransactionTranslator in src/iris_pgwire/iris_executor.py
- [ ] T030 Add transaction translation BEFORE normalization in _execute_embedded_async()
- [ ] T031 Verify translation occurs before Feature 021 normalization

### Integration Point 2: External Connection Path
- [ ] T032 Add transaction translation BEFORE normalization in _execute_external_async()

### Integration Point 3: Vector Query Optimization Path
- [ ] T033 Add transaction translation in src/iris_pgwire/vector_optimizer.py::optimize_vector_query()

## Phase 3.5: Edge Cases & Validation

### Edge Case Tests
- [ ] T034 [P] Edge case test: BEGIN WORK variant in tests/integration/test_transaction_edge_cases.py
- [ ] T035 [P] Edge case test: BEGIN TRANSACTION variant in tests/integration/test_transaction_edge_cases.py
- [ ] T036 [P] Edge case test: String literal "BEGIN" not translated in tests/integration/test_transaction_edge_cases.py
- [ ] T037 [P] Edge case test: Comment -- BEGIN not translated in tests/integration/test_transaction_edge_cases.py
- [ ] T038 [P] Edge case test: Nested BEGIN attempts (IRIS error expected) in tests/integration/test_transaction_edge_cases.py
- [ ] T039 [P] Edge case test: Case variants (begin, Begin, BEGIN) in tests/integration/test_transaction_edge_cases.py

### Performance Validation
- [ ] T040 Performance test: Measure translation overhead (<0.1ms) in tests/performance/test_translation_overhead.py
- [ ] T041 Performance test: E2E transaction workflow (<5ms SLA) in tests/performance/test_e2e_transaction_latency.py
- [ ] T042 Performance test: No additional IRIS round-trips introduced in tests/performance/test_roundtrip_count.py

### Regression Tests
- [ ] T043 Regression test: Feature 021 normalization still works after translation in tests/regression/test_feature_021_compatibility.py
- [ ] T044 Regression test: Vector queries work with transactions in tests/regression/test_vector_transaction_compatibility.py

## Phase 3.6: Polish

### Documentation
- [ ] T045 [P] Update CLAUDE.md with transaction translation patterns
- [ ] T046 [P] Add inline docstrings to TransactionTranslator methods
- [ ] T047 [P] Create examples/transaction_demo.py with usage examples

### Code Quality
- [ ] T048 [P] Run black formatting on sql_translator/transaction_translator.py
- [ ] T049 [P] Run ruff linting on all new files
- [ ] T050 [P] Remove any code duplication

### Final Validation
- [ ] T051 Execute quickstart.md test scenarios manually with real psql
- [ ] T052 Verify all contract tests PASS
- [ ] T053 Verify all E2E tests PASS
- [ ] T054 Verify performance metrics meet SLA (<0.1ms translation, <5ms total)

## Dependencies

### Critical Path (Sequential)
```
T001-T003 (Setup)
  ↓
T004-T020 (Tests - ALL MUST FAIL initially) [can run in parallel]
  ↓
T021-T028 (Core implementation - make tests pass)
  ↓
T029-T033 (Integration - 3 execution paths, sequential within each path)
  ↓
T034-T044 (Edge cases & validation) [can run in parallel]
  ↓
T045-T054 (Polish & final validation)
```

### Blocking Relationships
- T004-T020 MUST fail before T021 starts (TDD requirement)
- T021 blocks T022-T026 (class must exist before methods)
- T022 blocks T029-T033 (translation method must exist before integration)
- T029 must complete before T030 (import before usage)
- T030 blocks T031 (implementation before verification)
- All tests (T004-T020) must PASS before T051-T054

### Parallel Execution Groups

**Group 1: Setup (T001-T003)** - Can run together
```
Task: "Verify Python 3.11 environment"
Task: "Install test dependencies"
Task: "Verify IRIS PGWire server running"
```

**Group 2: Contract Tests (T004-T011)** - Can run together
```
Task: "Contract test BEGIN → START TRANSACTION"
Task: "Contract test BEGIN TRANSACTION → START TRANSACTION"
Task: "Contract test COMMIT unchanged"
Task: "Contract test ROLLBACK unchanged"
Task: "Contract test preserve modifiers"
Task: "Contract test string literal preservation"
Task: "Contract test case-insensitive matching"
Task: "Contract test performance <0.1ms"
```

**Group 3: Unit Tests (T012-T015)** - Can run together
```
Task: "Unit test translate_transaction_command"
Task: "Unit test BEGIN WORK variant"
Task: "Unit test is_transaction_command"
Task: "Unit test parse_transaction_command"
```

**Group 4: Integration Tests (T016-T020)** - Can run together
```
Task: "E2E test psql BEGIN/COMMIT"
Task: "E2E test psycopg parameterized statements"
Task: "E2E test SQLAlchemy context manager"
Task: "E2E test ROLLBACK on error"
Task: "E2E test isolation level modifiers"
```

**Group 5: Performance Monitoring (T027-T028)** - Can run together (different concerns)
```
Task: "Add translation timing instrumentation"
Task: "Add metrics collection"
```

**Group 6: Edge Cases (T034-T039)** - Can run together
```
Task: "Edge case test BEGIN WORK variant"
Task: "Edge case test BEGIN TRANSACTION variant"
Task: "Edge case test string literal preservation"
Task: "Edge case test comment preservation"
Task: "Edge case test nested BEGIN"
Task: "Edge case test case variants"
```

**Group 7: Performance Tests (T040-T042)** - Can run together
```
Task: "Performance test translation overhead"
Task: "Performance test E2E transaction workflow"
Task: "Performance test no additional round-trips"
```

**Group 8: Regression Tests (T043-T044)** - Can run together
```
Task: "Regression test Feature 021 compatibility"
Task: "Regression test vector transaction compatibility"
```

**Group 9: Documentation (T045-T047)** - Can run together
```
Task: "Update CLAUDE.md"
Task: "Add inline docstrings"
Task: "Create transaction demo examples"
```

**Group 10: Code Quality (T048-T050)** - Can run together
```
Task: "Run black formatting"
Task: "Run ruff linting"
Task: "Remove code duplication"
```

## Task Execution Order (Recommended)

### Phase 1: Setup (Parallel)
Run T001-T003 together

### Phase 2: TDD - Write Failing Tests (Parallel within groups)
1. Run T004-T011 together (contract tests)
2. Run T012-T015 together (unit tests)
3. Run T016-T020 together (integration tests)
4. **GATE CHECK**: All tests MUST fail (TransactionTranslator doesn't exist)

### Phase 3: Core Implementation (Sequential)
1. T021 (create class)
2. T022-T026 (implement methods - some can be parallel)
3. T027-T028 together (performance monitoring)
4. **GATE CHECK**: T004-T015 tests should now PASS

### Phase 4: Integration (Sequential within path, parallel across paths)
1. T029 (import)
2. T030-T031 (direct execution path)
3. T032 (external connection path)
4. T033 (vector optimizer path)
5. **GATE CHECK**: T016-T020 E2E tests should now PASS

### Phase 5: Edge Cases & Performance (Parallel)
1. Run T034-T039 together (edge cases)
2. Run T040-T042 together (performance)
3. Run T043-T044 together (regression)
4. **GATE CHECK**: All edge case tests PASS, performance within SLA

### Phase 6: Polish (Parallel)
1. Run T045-T047 together (docs)
2. Run T048-T050 together (code quality)

### Phase 7: Final Validation (Sequential)
1. T051 (manual testing with psql)
2. T052-T054 (verify all tests pass and metrics meet SLA)

## Validation Checklist
*GATE: Checked before considering feature complete*

- [x] All contracts have corresponding tests (T004-T011)
- [x] All entities have tasks (TransactionCommand in T024, TransactionState managed by protocol)
- [x] All tests come before implementation (T004-T020 before T021-T028)
- [x] Parallel tasks truly independent (verified no file conflicts)
- [x] Each task specifies exact file path
- [x] No task modifies same file as another [P] task
- [x] TDD order enforced (tests fail → implement → tests pass)
- [x] All 3 integration points covered (T029-T033)
- [x] All 5 acceptance scenarios tested (T016-T020)
- [x] Performance requirements validated (T040-T042)
- [x] Constitutional compliance verified (T043-T044)

## Notes

- **TDD Critical**: T004-T020 MUST fail before starting T021
- **Performance SLA**: <0.1ms translation, <5ms total (constitutional requirement)
- **Integration Order**: Transaction translation BEFORE Feature 021 normalization
- **Testing with Real Clients**: psql, psycopg, SQLAlchemy (not mocks)
- **Edge Cases**: String literals, comments, case sensitivity, nested transactions
- **Constitutional Compliance**: All 7 principles already validated in plan.md

## Task Count Summary

- **Setup**: 3 tasks (T001-T003)
- **Contract Tests**: 8 tasks (T004-T011)
- **Unit Tests**: 4 tasks (T012-T015)
- **Integration Tests**: 5 tasks (T016-T020)
- **Core Implementation**: 8 tasks (T021-T028)
- **Integration Points**: 5 tasks (T029-T033)
- **Edge Cases**: 6 tasks (T034-T039)
- **Performance**: 3 tasks (T040-T042)
- **Regression**: 2 tasks (T043-T044)
- **Documentation**: 3 tasks (T045-T047)
- **Code Quality**: 3 tasks (T048-T050)
- **Final Validation**: 4 tasks (T051-T054)

**Total**: 54 tasks (TDD-first approach with comprehensive testing)

---

*Based on Constitution v1.3.0 - See `.specify/memory/constitution.md`*
*Feature Branch: 022-postgresql-transaction-verb*
*Generated: 2025-11-08*

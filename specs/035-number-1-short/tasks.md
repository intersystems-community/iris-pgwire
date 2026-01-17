# Tasks: PostgreSQL DDL Compatibility (ENUM, RLS, Boolean Defaults)

**Input**: Design documents from `/specs/035-number-1-short/`
**Prerequisites**: plan.md (required), research.md, data-model.md, contracts/
**Branch**: `035-number-1-short`
**Date**: 2026-01-17

## Summary

This task list implements PostgreSQL DDL compatibility for ENUM types, Row Level Security statements, and boolean defaults. The approach follows TDD: contract tests first, then implementation to make tests pass.

**Organization**: Tasks are organized by translation category (not user story) since all three categories serve the same user story (ORM migration compatibility).

---

## Phase 1: Setup

- [x] T001 Create enum type registry module at `src/iris_pgwire/sql_translator/enum_registry.py`
- [x] T002 Create statement filter module at `src/iris_pgwire/sql_translator/statement_filter.py`
- [x] T003 [P] Create boolean translator module at `src/iris_pgwire/sql_translator/boolean_translator.py`
- [x] T004 [P] Create enum translator module at `src/iris_pgwire/sql_translator/enum_translator.py`

## Phase 2: Contract Tests (TDD - MUST FAIL BEFORE IMPLEMENTATION)

### ENUM Handling Tests
- [x] T005 [P] Contract test E-001: CREATE TYPE AS ENUM skip in `tests/contract/test_enum_translation.py`
- [x] T006 [P] Contract test E-002: Column type translation to VARCHAR(64) in `tests/contract/test_enum_translation.py`
- [x] T007 [P] Contract test E-003: Enum cast stripping in `tests/contract/test_enum_translation.py`
- [x] T008 [P] Contract test E-004: DROP TYPE skip for registered enums in `tests/contract/test_enum_translation.py`
- [x] T009 [P] Contract test E-005: Schema-qualified enum handling in `tests/contract/test_enum_translation.py`

### RLS Handling Tests
- [x] T010 [P] Contract test R-001: ENABLE ROW LEVEL SECURITY skip in `tests/contract/test_rls_handling.py`
- [x] T011 [P] Contract test R-002: DISABLE ROW LEVEL SECURITY skip in `tests/contract/test_rls_handling.py`
- [x] T012 [P] Contract test R-003: CREATE POLICY skip in `tests/contract/test_rls_handling.py`
- [x] T013 [P] Contract test R-004: DROP POLICY skip in `tests/contract/test_rls_handling.py`
- [x] T014 [P] Contract test R-005: Multi-statement batch with RLS in `tests/contract/test_rls_handling.py`

### Boolean Translation Tests
- [x] T015 [P] Contract test B-001/B-002: DEFAULT true/false translation in `tests/contract/test_boolean_defaults.py`
- [x] T016 [P] Contract test B-003/B-004: Case-insensitive matching in `tests/contract/test_boolean_defaults.py`
- [x] T017 [P] Contract test B-005: String literal protection in `tests/contract/test_boolean_defaults.py`
- [x] T018 [P] Contract test B-006/B-007: Comment protection in `tests/contract/test_boolean_defaults.py`
- [x] T019 [P] Contract test B-008: Multiple booleans in statement in `tests/contract/test_boolean_defaults.py`
- [x] T020 [P] Contract test B-009: Word boundary (truetype, falsehood) in `tests/contract/test_boolean_defaults.py`

## Phase 3: Core Implementation (Make Tests Pass)

### Enum Registry Implementation
- [x] T021 Implement EnumTypeRegistry class with register/lookup/clear in `src/iris_pgwire/sql_translator/enum_registry.py`

### Statement Filter Implementation
- [x] T022 Implement StatementFilter with skip detection patterns in `src/iris_pgwire/sql_translator/statement_filter.py`
- [x] T023 Add CREATE TYPE AS ENUM detection to StatementFilter in `src/iris_pgwire/sql_translator/statement_filter.py`
- [x] T024 Add RLS statement detection (ENABLE/DISABLE/CREATE POLICY/DROP POLICY) in `src/iris_pgwire/sql_translator/statement_filter.py`
- [x] T025 Add DROP TYPE detection for registered enums in `src/iris_pgwire/sql_translator/statement_filter.py`

### Enum Translator Implementation
- [x] T026 Implement EnumTranslator.translate_column_types() in `src/iris_pgwire/sql_translator/enum_translator.py`
- [x] T027 Implement EnumTranslator.strip_enum_casts() in `src/iris_pgwire/sql_translator/enum_translator.py`
- [x] T028 Handle schema-qualified enum types and quoted identifiers in `src/iris_pgwire/sql_translator/enum_translator.py`

### Boolean Translator Implementation
- [x] T029 Implement BooleanTranslator.translate() with context safety in `src/iris_pgwire/sql_translator/boolean_translator.py`
- [x] T030 Add string literal detection to avoid false positives in `src/iris_pgwire/sql_translator/boolean_translator.py`
- [x] T031 Add comment detection (line and block) to avoid false positives in `src/iris_pgwire/sql_translator/boolean_translator.py`

## Phase 4: Pipeline Integration

- [x] T032 Add EnumTypeRegistry to SQLTranslator.__init__ in `src/iris_pgwire/sql_translator/normalizer.py`
- [x] T033 Integrate StatementFilter at start of normalize_sql pipeline in `src/iris_pgwire/sql_translator/normalizer.py`
- [x] T034 Integrate EnumTranslator after StatementFilter in `src/iris_pgwire/sql_translator/normalizer.py`
- [x] T035 Integrate BooleanTranslator in normalize_sql pipeline in `src/iris_pgwire/sql_translator/normalizer.py`
- [x] T036 Return skip result tuple when statement is filtered in `src/iris_pgwire/sql_translator/normalizer.py`

## Phase 5: E2E Integration Tests

- [x] T037 [P] E2E test: Full ENUM workflow (CREATE TYPE → table → column → DROP) in `tests/integration/test_enum_e2e.py`
- [x] T038 [P] E2E test: RLS statements in migration batch in `tests/integration/test_rls_e2e.py`
- [x] T039 [P] E2E test: Boolean defaults in CREATE TABLE and ALTER TABLE in `tests/integration/test_boolean_e2e.py`
- [x] T040 [P] E2E test: Drizzle-style migration patterns in `tests/integration/test_drizzle_migration.py`

## Phase 6: Validation & Polish

- [x] T041 Run full test suite to verify no regressions (`pytest tests/ -v --ignore=tests/archive`)
- [x] T042 Performance validation: <5ms translation overhead per statement (achieved 0.12ms avg)
- [x] T043 Execute quickstart.md validation steps manually
- [x] T044 Update `src/iris_pgwire/sql_translator/__init__.py` to export new classes

## Phase 7: Downstream Cleanup (Post-Release)

- [ ] T045 Remove enum/RLS/boolean handling from `sim/iris/sim_sql_patch.py` after upstream release
- [ ] T046 Test sim project migrations with updated iris-pgwire package

---

## Dependencies

```
Phase 1 (Setup) ──► Phase 2 (Tests) ──► Phase 3 (Implementation) ──► Phase 4 (Integration)
                                                                           │
                                                                           ▼
                                                                   Phase 5 (E2E Tests)
                                                                           │
                                                                           ▼
                                                                   Phase 6 (Validation)
                                                                           │
                                                                           ▼
                                                                   Phase 7 (Cleanup)
```

### Task Dependencies

| Task | Depends On | Reason |
|------|------------|--------|
| T005-T020 | T001-T004 | Test files import new modules |
| T021-T031 | T005-T020 | TDD: tests must exist first |
| T032-T036 | T021-T031 | Integration requires implementations |
| T037-T040 | T032-T036 | E2E tests require pipeline integration |
| T041-T044 | T037-T040 | Validation after E2E tests pass |
| T045-T046 | T041-T044 | Cleanup after upstream validation |

---

## Parallel Execution Examples

### Phase 1 (Setup) - All parallel
```bash
# Launch T001-T004 together (different files):
# T001: enum_registry.py
# T002: statement_filter.py
# T003: boolean_translator.py
# T004: enum_translator.py
```

### Phase 2 (Tests) - All parallel
```bash
# Launch T005-T020 together (different test files):
# T005-T009: test_enum_translation.py (same file, but independent test functions)
# T010-T014: test_rls_handling.py
# T015-T020: test_boolean_defaults.py
```

### Phase 5 (E2E) - All parallel
```bash
# Launch T037-T040 together (different test files):
# T037: test_enum_e2e.py
# T038: test_rls_e2e.py
# T039: test_boolean_e2e.py
# T040: test_drizzle_migration.py
```

---

## Implementation Strategy

### MVP (Minimum Viable Product)
**Tasks T001-T036**: Core translation capability
- All three translation categories implemented
- Pipeline integration complete
- Contract tests passing

### Full Validation
**Tasks T037-T044**: E2E tests and validation
- Real migration pattern tests
- Performance validation
- No regression in existing 171 client tests

### Downstream Integration
**Tasks T045-T046**: Remove duplicate code from sim
- Only after iris-pgwire release with this feature

---

## Task Counts

| Phase | Count | Parallel |
|-------|-------|----------|
| Phase 1: Setup | 4 | 4 |
| Phase 2: Contract Tests | 16 | 16 |
| Phase 3: Implementation | 11 | 0 |
| Phase 4: Integration | 5 | 0 |
| Phase 5: E2E Tests | 4 | 4 |
| Phase 6: Validation | 4 | 0 |
| Phase 7: Cleanup | 2 | 0 |
| **Total** | **46** | **24** |

---

## Notes

- [P] tasks = different files, no dependencies on incomplete tasks
- Verify contract tests FAIL before implementing (TDD)
- Commit after each phase completes
- All new modules placed in `src/iris_pgwire/sql_translator/`
- Tests follow existing patterns in `tests/contract/` and `tests/integration/`
- Performance target: <5ms translation overhead (constitutional requirement)

---

## Validation Checklist

- [ ] All contracts have corresponding tests (T005-T020)
- [ ] All 3 translation categories implemented
- [ ] All tests come before implementation (TDD order)
- [ ] Parallel tasks truly independent
- [ ] Each task specifies exact file path
- [ ] No task modifies same file as another [P] task
- [ ] 171 existing client tests still pass
- [ ] 64 previously failing statements now succeed

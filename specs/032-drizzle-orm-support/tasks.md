# Tasks: Drizzle ORM Support

**Feature**: 032-drizzle-orm-support
**Input**: Design documents from `/specs/032-drizzle-orm-support/`
**Prerequisites**: plan.md, research.md, data-model.md, contracts/, quickstart.md

## Summary

This is a **verification feature** - validating that existing IRIS PGWire capabilities (from Feature 031) work with Drizzle ORM. Tasks focus on creating a demo project, running verification tests, and documenting results.

**User Stories** (from spec.md acceptance scenarios):
- **US1**: Introspection - drizzle-kit introspect generates accurate schema.ts
- **US2**: INSERT with .returning() returns inserted row with ID
- **US3**: SELECT queries return correct data with type mapping
- **US4**: UPDATE with .returning() returns updated row
- **US5**: DELETE with .returning() returns deleted row data
- **US6**: Transactions commit/rollback correctly
- **US7**: Type mapping roundtrip preserves data integrity

---

## Phase 1: Setup

- [ ] T001 Create Drizzle demo project structure at examples/drizzle-iris-demo/
- [ ] T002 Initialize Node.js project with package.json in examples/drizzle-iris-demo/
- [ ] T003 [P] Install dependencies: drizzle-orm, postgres, drizzle-kit, typescript in examples/drizzle-iris-demo/
- [ ] T004 [P] Create TypeScript config at examples/drizzle-iris-demo/tsconfig.json
- [ ] T005 [P] Create Drizzle config at examples/drizzle-iris-demo/drizzle.config.ts
- [ ] T006 Create test table in IRIS via verify_demo.sql or direct SQL

---

## Phase 2: Foundational (MUST complete before user stories)

- [ ] T007 Restart IRIS PGWire container to ensure latest code is loaded
- [ ] T008 Verify IRIS PGWire is accepting connections on localhost:5432
- [ ] T009 [P] Create database client module at examples/drizzle-iris-demo/src/db.ts

---

## Phase 3: User Story 1 - Introspection [US1]

**Goal**: Verify drizzle-kit introspect successfully generates schema.ts from IRIS tables

**Independent Test Criteria**: Run `npx drizzle-kit introspect` and verify schema.ts is generated with correct table definitions

- [ ] T010 [US1] Run drizzle-kit introspect against IRIS PGWire
- [ ] T011 [US1] Verify generated schema.ts exists at examples/drizzle-iris-demo/src/schema.ts
- [ ] T012 [US1] Verify schema.ts contains correct table definition with columns
- [ ] T013 [US1] Verify primary key is correctly identified in schema.ts
- [ ] T014 [US1] Document introspection results in examples/drizzle-iris-demo/RESULTS.md

---

## Phase 4: User Story 2 - INSERT with RETURNING [US2]

**Goal**: Verify INSERT operations with .returning() work correctly

**Independent Test Criteria**: Execute db.insert().returning() and verify inserted row is returned with auto-generated ID

- [ ] T015 [US2] Create INSERT test script at examples/drizzle-iris-demo/src/test-insert.ts
- [ ] T016 [US2] Execute INSERT with .returning() and capture result
- [ ] T017 [US2] Verify returned row contains auto-generated ID > 0
- [ ] T018 [US2] Verify all columns are returned including timestamps
- [ ] T019 [US2] Document INSERT results in examples/drizzle-iris-demo/RESULTS.md

---

## Phase 5: User Story 3 - SELECT Queries [US3]

**Goal**: Verify SELECT queries return correct data with proper type mapping

**Independent Test Criteria**: Execute db.select().where() and verify correct row is returned with expected values

- [ ] T020 [US3] Add SELECT test to examples/drizzle-iris-demo/src/test-select.ts
- [ ] T021 [US3] Execute SELECT with WHERE clause using parameterized query
- [ ] T022 [US3] Verify returned row matches inserted data
- [ ] T023 [US3] Verify type mapping (integer, varchar, timestamp)
- [ ] T024 [US3] Document SELECT results in examples/drizzle-iris-demo/RESULTS.md

---

## Phase 6: User Story 4 - UPDATE with RETURNING [US4]

**Goal**: Verify UPDATE operations with .returning() work correctly

**Independent Test Criteria**: Execute db.update().returning() and verify updated row is returned

- [ ] T025 [US4] Create UPDATE test script at examples/drizzle-iris-demo/src/test-update.ts
- [ ] T026 [US4] Execute UPDATE with .returning() and capture result
- [ ] T027 [US4] Verify returned row contains updated values
- [ ] T028 [US4] Verify unchanged columns are preserved
- [ ] T029 [US4] Document UPDATE results in examples/drizzle-iris-demo/RESULTS.md

---

## Phase 7: User Story 5 - DELETE with RETURNING [US5]

**Goal**: Verify DELETE operations with .returning() work correctly

**Independent Test Criteria**: Execute db.delete().returning() and verify deleted row data is returned

- [ ] T030 [US5] Create DELETE test script at examples/drizzle-iris-demo/src/test-delete.ts
- [ ] T031 [US5] Execute DELETE with .returning() and capture result
- [ ] T032 [US5] Verify returned row contains pre-delete data
- [ ] T033 [US5] Verify row no longer exists after delete
- [ ] T034 [US5] Document DELETE results in examples/drizzle-iris-demo/RESULTS.md

---

## Phase 8: User Story 6 - Transactions [US6]

**Goal**: Verify Drizzle transactions commit and rollback correctly

**Independent Test Criteria**: Execute db.transaction() with commit and rollback scenarios

- [ ] T035 [US6] Create transaction test script at examples/drizzle-iris-demo/src/test-transaction.ts
- [ ] T036 [US6] Execute transaction with multiple operations and verify COMMIT
- [ ] T037 [US6] Execute transaction with simulated error and verify ROLLBACK
- [ ] T038 [US6] Verify data integrity after commit (rows exist)
- [ ] T039 [US6] Verify data integrity after rollback (no partial data)
- [ ] T040 [US6] Document transaction results in examples/drizzle-iris-demo/RESULTS.md

---

## Phase 9: User Story 7 - Type Mapping [US7]

**Goal**: Verify type mapping roundtrip preserves data integrity

**Independent Test Criteria**: Insert various types, read back, verify values match exactly

- [ ] T041 [US7] Create type mapping test at examples/drizzle-iris-demo/src/test-types.ts
- [ ] T042 [US7] Test INTEGER roundtrip (insert → select → compare)
- [ ] T043 [US7] Test VARCHAR roundtrip with special characters
- [ ] T044 [US7] Test TIMESTAMP roundtrip with timezone handling
- [ ] T045 [US7] Test BOOLEAN/BIT roundtrip
- [ ] T046 [US7] Document type mapping results in examples/drizzle-iris-demo/RESULTS.md

---

## Phase 10: Integration & Polish

- [ ] T047 Create unified test runner at examples/drizzle-iris-demo/src/test-crud.ts (combines all tests)
- [ ] T048 [P] Create Python integration test at tests/integration/test_drizzle_compatibility.py
- [ ] T049 [P] Update README.md with Drizzle ORM instructions
- [ ] T050 Consolidate RESULTS.md with pass/fail summary
- [ ] T051 Update checklists/requirements.md with verification status
- [ ] T052 Clean up test data from IRIS database

---

## Dependencies

```
Phase 1 (Setup) → Phase 2 (Foundational) → User Stories (parallel possible)

T001 → T002 → T003, T004, T005 (parallel)
T006 → T007 → T008
T009 → All user story phases

User Stories can run in parallel after T009:
- US1 (T010-T014): Introspection
- US2-US5 (T015-T034): CRUD operations (sequential within story)
- US6 (T035-T040): Transactions
- US7 (T041-T046): Type mapping

Polish (T047-T052) after all user stories complete
```

---

## Parallel Execution Examples

### Setup Phase (launch T003, T004, T005 together after T002):
```
Task: "Install dependencies in examples/drizzle-iris-demo/"
Task: "Create TypeScript config at examples/drizzle-iris-demo/tsconfig.json"
Task: "Create Drizzle config at examples/drizzle-iris-demo/drizzle.config.ts"
```

### User Stories (after T009, these can run in parallel):
```
Task: "[US1] Run drizzle-kit introspect against IRIS PGWire"
Task: "[US6] Create transaction test script"
Task: "[US7] Create type mapping test"
```

### Polish Phase (launch T048, T049 together):
```
Task: "Create Python integration test at tests/integration/test_drizzle_compatibility.py"
Task: "Update README.md with Drizzle ORM instructions"
```

---

## Implementation Strategy

### MVP Scope (User Story 1 only)
For quick validation, complete just US1 (Introspection):
- T001-T009 (Setup + Foundational)
- T010-T014 (US1: Introspection)

If introspection works, existing catalog implementation is validated. Proceed to CRUD testing.

### Incremental Delivery
1. **Checkpoint 1**: Introspection works (US1)
2. **Checkpoint 2**: Basic CRUD works (US2-US5)
3. **Checkpoint 3**: Advanced features work (US6, US7)
4. **Checkpoint 4**: Documentation complete (Polish)

### Gap Identification
If any user story fails, document the specific failure:
1. Capture the exact error message
2. Identify the SQL query that failed
3. Compare to Prisma behavior (Feature 031)
4. Create fix task if server-side change needed

---

## Validation Checklist

- [x] All user stories have corresponding task phases
- [x] Each phase has independent test criteria
- [x] Tasks specify exact file paths
- [x] Parallel tasks truly independent ([P] markers)
- [x] Documentation tasks included
- [x] Cleanup task included (T052)

---

## Notes

- This is a **verification feature** - no server-side code changes expected
- If tests fail, create follow-up tasks for fixes (not included here)
- All tests use the demo project at `examples/drizzle-iris-demo/`
- Results documented in `RESULTS.md` for each phase
- Commit after each phase completion

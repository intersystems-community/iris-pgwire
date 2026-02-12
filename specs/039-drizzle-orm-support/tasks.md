# Tasks: Drizzle ORM DDL Translation Support

**Input**: Design documents from `/specs/039-drizzle-orm-support/`
**Prerequisites**: plan.md, spec.md (4 user stories), research.md, data-model.md, contracts/api-contracts.md, quickstart.md

**Organization**: Tasks are grouped by user story to enable independent implementation and testing of each story.

**Tests**: Integration tests are included to verify end-to-end behavior per user story.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies)
- **[Story]**: Which user story this task belongs to (e.g., US1, US2, US3, US4)
- Include exact file paths in descriptions

## Project Structure

Single project layout (from plan.md):
```
src/iris_pgwire/
├── sql_translator/
│   ├── ddl_translator.py      # DDL translation logic
│   ├── ddl_parser.py           # PostgreSQL DDL parsing
│   ├── type_translator.py      # Type mapping logic
│   ├── constraint_translator.py # Constraint translation
│   ├── reserved_words.py       # Reserved word checker
│   └── translator.py           # Existing (extend for DDL)
├── migrations/
│   ├── executor.py             # Migration execution
│   └── __main__.py             # CLI entry point
└── config.py                   # Configuration classes

tests/
├── integration/
│   └── test_drizzle_migration.py
├── unit/
│   ├── test_ddl_translator.py
│   ├── test_type_translator.py
│   └── test_reserved_words.py
└── fixtures/
    └── drizzle_migrations.py
```

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Project initialization and basic structure

- [x] T001 Create directory structure for DDL translation in src/iris_pgwire/sql_translator/
- [x] T002 Create directory structure for migrations executor in src/iris_pgwire/migrations/
- [x] T003 [P] Create test directory structure in tests/integration/, tests/unit/, tests/fixtures/
- [x] T004 [P] Add development dependencies (sqlparse, pytest fixtures) to pyproject.toml

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Core infrastructure that MUST be complete before ANY user story can be implemented

**⚠️ CRITICAL**: No user story work can begin until this phase is complete

- [ ] T005 Create DDLTranslationError exception class in src/iris_pgwire/sql_translator/ddl_translator.py
- [ ] T006 [P] Create DDLTranslationConfig dataclass in src/iris_pgwire/config.py
- [x] T007 [P] Create ReservedWordChecker class skeleton in src/iris_pgwire/sql_translator/reserved_words.py
- [x] T008 Load IRIS reserved words list from documentation into reserved_words.py resource file
- [x] T009 Implement ReservedWordChecker.is_reserved() and quote_if_needed() methods in reserved_words.py
- [x] T010 Create TypeMappingEntry dataclass in src/iris_pgwire/sql_translator/type_translator.py
- [x] T011 Define DDL_TYPE_MAPPINGS dictionary with 20+ PostgreSQL→IRIS mappings in src/iris_pgwire/sql_translator/type_translator.py
- [x] T012 Define TYPE_PRECISION_LIMITS dictionary (NUMERIC max 38, VARCHAR max 32767) in src/iris_pgwire/sql_translator/type_translator.py
- [ ] T013 Create DDLStatement dataclass in src/iris_pgwire/sql_translator/ddl_translator.py
- [ ] T014 Create ColumnDefinition dataclass in src/iris_pgwire/sql_translator/ddl_parser.py
- [ ] T015 Create ConstraintDefinition dataclass in src/iris_pgwire/sql_translator/ddl_parser.py
- [ ] T016 Create IndexDefinition dataclass in src/iris_pgwire/sql_translator/ddl_parser.py
- [ ] T017 Create MigrationFile dataclass with MigrationStatus enum in src/iris_pgwire/migrations/executor.py
- [ ] T018 Create MigrationResult dataclass in src/iris_pgwire/migrations/executor.py
- [X] T019 Create test fixtures in tests/fixtures/drizzle_migrations.py (sample_drizzle_migration, ddl_translator)

**Checkpoint**: Foundation ready - user story implementation can now begin in parallel

---

## Phase 3: User Story 1 - Automatic Schema Sync (Priority: P1) 🎯 MVP

**Goal**: Developers can run Drizzle-generated CREATE TABLE statements containing reserved words and PostgreSQL types against IRIS without manual SQL rewriting

**Independent Test**: Generate a Drizzle migration with CREATE TABLE using reserved word columns ("level", "key") and PostgreSQL types (text, uuid, boolean), run through iris-pgwire, verify table created correctly in IRIS

### Integration Tests for User Story 1

> **NOTE: Write these tests FIRST, ensure they FAIL before implementation**

- [x] T200 [P] [US1] Integration test: Basic CREATE TABLE with type translation in tests/integration/test_drizzle_migration.py::test_basic_table_creation
- [x] T201 [P] [US1] Integration test: Reserved word auto-quoting in tests/integration/test_drizzle_migration.py::test_reserved_word_auto_quoting
- [x] T202 [P] [US1] Integration test: Primary key constraint translation in tests/integration/test_drizzle_migration.py::test_primary_key_constraint
- [x] T206 [US1] Integration test: Transaction rollback on failure in tests/integration/test_drizzle_migration.py::test_transaction_rollback_on_failure
- [x] T207 [US1] Integration test: Migration journal tracking in tests/integration/test_drizzle_migration.py::test_migration_journal_tracking

### Implementation for User Story 1

- [x] T020 [US1] Implement DDLParser.parse() for CREATE TABLE statements using sqlparse in src/iris_pgwire/sql_translator/ddl_parser.py
- [x] T021 [US1] Implement DDLParser._parse_create_table() to extract table metadata in src/iris_pgwire/sql_translator/ddl_parser.py
- [x] T022 [US1] Implement DDLParser._parse_column_definition() to parse column metadata (type, default, primary key) in src/iris_pgwire/sql_translator/ddl_parser.py
- [x] T025 [US1] Create TypeTranslator class in src/iris_pgwire/sql_translator/type_translator.py
- [x] T026 [US1] Implement TypeTranslator.translate_type() with basic type mappings (text, boolean, integer) in type_translator.py
- [x] T027 [US1] Create DDLTranslator class in src/iris_pgwire/sql_translator/ddl_translator.py
- [x] T028 [US1] Implement MigrationExecutor.create_journal_table() to create __drizzle_migrations table in executor.py
- [x] T029 [US1] Implement MigrationExecutor.is_migration_applied() to check journal before running a migration in executor.py
- [x] T030 [US1] Implement MigrationExecutor.record_migration() to insert migration hash into journal in executor.py
- [x] T031 [US1] Implement MigrationExecutor._begin_transaction() and _commit_transaction() for IRIS transactions in executor.py
- [ ] T032 [US1] Implement DDLTranslator.__init__() with reserved_words and type_mapping initialization in ddl_translator.py
- [ ] T033 [US1] Implement DDLTranslator.translate_statement() for CREATE TABLE with reserved word quoting in ddl_translator.py
- [ ] T034 [US1] Implement DDLTranslator.translate_migration_file() to parse and translate all statements in a .sql file in ddl_translator.py
- [x] T035 [US1] Create MigrationExecutor class skeleton in src/iris_pgwire/migrations/executor.py
- [x] T036 Implement DDLParser._parse_alter_table() stub in src/iris_pgwire/sql_translator/ddl_parser.py
- [x] T037 Implement DDLTranslator.translate_alter_table() stub in src/iris_pgwire/sql_translator/ddl_translator.py
- [x] T038 Implement DDLTranslator.translate_drop_table() stub in src/iris_pgwire/sql_translator/ddl_translator.py
- [ ] T039 [US1] Add transaction rollback logic on failure to execute_migration() in executor.py
- [ ] T040 [US1] Add journal update logic after successful COMMIT to execute_migration() in executor.py
- [ ] T041 [US1] Implement MigrationExecutor.execute_migrations() to run all pending migrations in directory in executor.py

**Checkpoint**: At this point, User Story 1 should be fully functional - CREATE TABLE statements with reserved words translate and execute successfully

---

## Phase 4: User Story 2 - PostgreSQL Type Mapping (Priority: P1)

**Goal**: Drizzle tables using standard PostgreSQL types (text, boolean, jsonb, timestamp with time zone, uuid, numeric with precision) translate correctly to IRIS-compatible types

**Independent Test**: Create table with all common PostgreSQL types, insert/query data, verify correct type semantics in IRIS

### Integration Tests for User Story 2

- [x] T203 [P] [US2] Integration test: Type mapping for text, boolean, jsonb in tests/integration/test_drizzle_migration.py::test_common_type_mappings
- [x] T204 [P] [US2] Integration test: Timestamp with time zone handling in tests/integration/test_drizzle_migration.py::test_timestamp_timezone_mapping
- [x] T205 [P] [US2] Integration test: UUID type and gen_random_uuid() default in tests/integration/test_drizzle_migration.py::test_uuid_type_and_default

### Implementation for User Story 2

- [x] T042 [P] [US2] Extend DDL_TYPE_MAPPINGS with jsonb, timestamp with time zone, uuid in type_mapping.py
- [x] T043 [P] [US2] Extend DDL_TYPE_MAPPINGS with numeric, serial, bigserial types in type_mapping.py
- [x] T044 [US2] Implement TypeTranslator.translate_type() for jsonb → JSON mapping in type_translator.py
- [x] T045 [US2] Implement TypeTranslator.translate_type() for timestamp with time zone → TIMESTAMP in type_translator.py
- [x] T046 [US2] Implement TypeTranslator.translate_type() for uuid → UUID in type_translator.py
- [x] T047 [US2] Implement TypeTranslator.translate_type() for serial → INTEGER with AUTO_INCREMENT in type_translator.py
- [x] T048 [US2] Add DEFAULT value translation (gen_random_uuid(), CURRENT_TIMESTAMP) to DDLParser in ddl_parser.py
- [x] T049 [US2] Update DDLTranslator.translate_statement() to handle DEFAULT clauses with function calls in ddl_translator.py
- [x] T050 [US2] Add data insertion/query integration test to verify type semantics in test_drizzle_migration.py

**Checkpoint**: At this point, User Stories 1 AND 2 should both work - full CREATE TABLE support with complete type mapping

---

## Phase 5: User Story 3 - Index Creation Compatibility (Priority: P2)

**Goal**: Drizzle-generated CREATE INDEX statements execute successfully against IRIS, with clear errors on unsupported PostgreSQL-specific features (WHERE clauses, INCLUDE columns, expression indexes)

**Independent Test**: Run Drizzle-generated CREATE INDEX statements (single-column, multi-column, unique) and verify indexes created; test that unsupported features error with clear guidance

### Integration Tests for User Story 3

-- [x] T051 [P] [US3] Integration test: Basic CREATE INDEX single-column in tests/integration/test_drizzle_migration.py::test_basic_index_creation
-- [x] T052 [P] [US3] Integration test: CREATE UNIQUE INDEX multi-column in tests/integration/test_drizzle_migration.py::test_unique_multicolumn_index
-- [x] T053 [P] [US3] Integration test: Error on partial index with WHERE clause in tests/integration/test_drizzle_migration.py::test_unsupported_index_where_clause
-- [x] T054 [P] [US3] Integration test: Error on INCLUDE columns in tests/integration/test_drizzle_migration.py::test_unsupported_index_include

### Implementation for User Story 3

-- [x] T055 [P] [US3] Extend DDLParser.parse() to handle CREATE INDEX statements in ddl_parser.py
-- [x] T056 [US3] Implement IndexDefinition validation (detect WHERE clause, INCLUDE, expression indexes) in ddl_parser.py
-- [x] T057 [US3] Add CREATE INDEX translation logic to DDLTranslator.translate_statement() in ddl_translator.py
-- [x] T058 [US3] Implement error on unsupported index features with suggested_fix in ddl_translator.py
-- [x] T059 [US3] Add DROP INDEX support to DDLParser and DDLTranslator in ddl_parser.py and ddl_translator.py
-- [x] T060 [US3] Update quickstart.md with index creation examples and troubleshooting

**Checkpoint**: All P1+P2 user stories functional - tables, types, and indexes fully supported

---

## Phase 6: User Story 4 - Reserved Word Handling (Priority: P2)

**Goal**: When Drizzle SQL contains unquoted identifiers matching IRIS reserved words (but not PostgreSQL), translator automatically quotes them without schema modifications

**Independent Test**: Create table with columns named "level", "trigger", "key", "value", "state" (IRIS reserved but not PostgreSQL), verify DDL executes and queries work

### Integration Tests for User Story 4

- [x] T061 [P] [US4] Integration test: Auto-quoting of unquoted reserved words in tests/integration/test_drizzle_migration.py::test_reserved_word_auto_quoting
- [x] T062 [P] [US4] Integration test: Query reserved word columns after creation in tests/integration/test_drizzle_migration.py::test_reserved_word_column_queries
- [x] T063 [P] [US4] Integration test: ALTER TABLE ADD COLUMN with reserved word in tests/integration/test_drizzle_migration.py::test_alter_add_reserved_word_column

### Implementation for User Story 4

[x] T064 [P] [US4] Add ALTER TABLE ADD COLUMN parsing to DDLParser in ddl_parser.py
[x] T065 [P] [US4] Add ALTER TABLE DROP COLUMN parsing to DDLParser in ddl_parser.py
[x] T066 [P] [US4] Add ALTER TABLE RENAME COLUMN parsing to DDLParser in ddl_parser.py
[x] T067 [US4] Implement ALTER TABLE translation with reserved word quoting in DDLTranslator in ddl_translator.py
[x] T068 [US4] Apply ReservedWordChecker to all identifiers (table, column, index names) in DDLTranslator in ddl_translator.py
[x] T069 [US4] Add comprehensive reserved word test suite in tests/unit/test_reserved_words.py
[x] T070 [US4] Update quickstart.md with reserved word handling examples

**Checkpoint**: All user stories independently functional - complete DDL translation support

---

## Phase 7: Cross-Cutting Enhancements

**Purpose**: Features that span multiple user stories and improve overall system quality

### Type Precision Validation (Spec Clarification 1)

- [ ] T071 [P] Implement precision validation within TypeTranslator.translate_type() - error when NUMERIC precision >38 or VARCHAR length >32767 in type_translator.py
- [ ] T072 Add DDLTranslationError with suggested_fix when precision validation fails in TypeTranslator.translate_type() in type_translator.py
- [ ] T073 Add integration test for numeric precision exceeded error in tests/integration/test_drizzle_migration.py::test_type_precision_error

### Transaction Semantics & Concurrent Execution (Spec Clarifications 2 & 4)

- [x] T032 Implement MigrationExecutor._acquire_lock() to obtain an exclusive lock via `LOCK TABLE __drizzle_migrations IN EXCLUSIVE MODE` with timeout in src/iris_pgwire/migrations/executor.py
- [x] T033 Implement MigrationExecutor._release_lock() placeholder to document automatic lock release upon transaction end in src/iris_pgwire/migrations/executor.py
- [x] T034 Implement MigrationExecutor.execute_migration() with locking, translation, transaction semantics, and journaling (all-or-nothing, rollback on failure) in src/iris_pgwire/migrations/executor.py
- [ ] T075 [P] Implement database-level advisory locking via LOCK TABLE in MigrationExecutor in executor.py
- [ ] T076 Add lock timeout configuration to DDLTranslationConfig in config.py
- [ ] T077 Implement lock acquisition with timeout in MigrationExecutor.execute_migration() in executor.py
- [ ] T078 Add integration test for concurrent migration locking in tests/integration/test_drizzle_migration.py::test_concurrent_migration_locking
- [ ] T079 Add integration test for transaction rollback on partial failure in tests/integration/test_drizzle_migration.py::test_transaction_rollback_on_failure

### Advanced Index Feature Errors (Spec Clarification 3)

- [ ] T080 [P] Implement WHERE clause detection in IndexDefinition validation in ddl_parser.py
- [ ] T081 [P] Implement INCLUDE columns detection in IndexDefinition validation in ddl_parser.py
- [ ] T082 [P] Implement expression index detection in IndexDefinition validation in ddl_parser.py
- [ ] T083 Add structured error with suggested_fix for each unsupported index feature in ddl_translator.py

### Constraint Translation

- [ ] T084 [P] Create ConstraintTranslator class in src/iris_pgwire/sql_translator/constraint_translator.py
- [ ] T085 Implement translate_primary_key() in constraint_translator.py
- [ ] T086 Implement translate_foreign_key() with CASCADE/RESTRICT support in constraint_translator.py
- [ ] T087 Implement translate_unique() in constraint_translator.py
- [ ] T088 Implement translate_check() in constraint_translator.py
- [ ] T089 Integrate ConstraintTranslator into DDLTranslator for CREATE TABLE in ddl_translator.py
- [ ] T089 Add DROP TABLE with CASCADE/RESTRICT translation in ddl_translator.py

### Edge Case Handling

- [ ] T090 [P] Document schema name conflict resolution in quickstart.md troubleshooting section
- [ ] T091 Add validation for IRIS system schema conflicts (SQLUser, %SYS) in DDLTranslator in ddl_translator.py
- [ ] T092 Document large migration file limits (statement count, DEFAULT value size) in quickstart.md

### Integration with Existing SQLTranslator

- [ ] T093 Add enable_ddl_translation flag to SQLTranslator.__init__() in sql_translator/translator.py
- [ ] T094 Implement SQLTranslator._is_ddl_statement() detection in translator.py
- [ ] T095 Route DDL statements to DDLTranslator when flag enabled in SQLTranslator.normalize_sql() in translator.py
- [ ] T096 Add integration test for SQLTranslator DDL routing in tests/integration/test_sql_translator_ddl.py

---

## Phase 8: CLI & Developer Experience

**Purpose**: Command-line interface and documentation for end-users

### CLI Implementation

- [ ] T097 [P] Create CLI entry point in src/iris_pgwire/migrations/__main__.py
- [ ] T098 Implement --migrations-dir argument parsing in __main__.py
- [ ] T099 Implement --host, --port, --user, --password arguments in __main__.py
- [ ] T100 Implement --dry-run mode (translate without executing) in __main__.py
- [ ] T101 Implement --status mode (show applied/pending migrations) in __main__.py
- [ ] T102 Implement --json output format for scripting in __main__.py
- [ ] T103 Add progress callbacks for migration execution in __main__.py

### Unit Test Coverage

- [ ] T104 [P] Unit tests for DDLParser.parse() in tests/unit/test_ddl_parser.py
- [ ] T105 [P] Unit tests for TypeTranslator.translate_type() in tests/unit/test_type_translator.py
- [ ] T106 [P] Unit tests for ConstraintTranslator methods in tests/unit/test_constraint_translator.py
- [ ] T107 [P] Unit tests for ReservedWordChecker in tests/unit/test_reserved_words.py
- [ ] T108 [P] Unit tests for precision validation in tests/unit/test_type_translator.py

---

## Phase 9: Polish & Documentation

**Purpose**: Final improvements and documentation updates

- [ ] T109 [P] Update main README.md with Drizzle DDL translation feature overview
- [ ] T110 [P] Add migration troubleshooting section to quickstart.md
- [ ] T111 [P] Add Docker Compose integration example to quickstart.md (updated from provided version)
- [ ] T112 [P] Create CHANGELOG entry for v1.4.0 with Drizzle support
- [ ] T113 Code cleanup: Remove debug logging from production code
- [ ] T114 Code cleanup: Ensure all error messages follow structured format
- [ ] T115 Run full test suite and ensure 100% pass rate
- [ ] T116 Run ruff and black formatters across all new code
- [ ] T117 Update type hints for all public API methods
- [ ] T118 Add docstrings to all public classes and methods
- [ ] T119 Validate quickstart.md examples against actual implementation
- [ ] T120 Security review: Validate SQL injection prevention in identifier quoting

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: No dependencies - can start immediately
- **Foundational (Phase 2)**: Depends on Setup completion - BLOCKS all user stories
- **User Stories (Phases 3-6)**: All depend on Foundational phase completion
  - User stories can proceed in parallel (if staffed)
  - Or sequentially in priority order (US1 → US2 → US3 → US4)
- **Cross-Cutting (Phase 7)**: Depends on User Stories 1-4
- **CLI (Phase 8)**: Depends on User Stories 1-4
- **Polish (Phase 9)**: Depends on all previous phases

### User Story Dependencies

- **User Story 1 (P1)**: Can start after Foundational (Phase 2) - No dependencies on other stories
- **User Story 2 (P1)**: Can start after Foundational (Phase 2) - Extends US1 but independently testable
- **User Story 3 (P2)**: Can start after Foundational (Phase 2) - Extends US1 but independently testable
- **User Story 4 (P2)**: Can start after Foundational (Phase 2) - Enhances US1/US3 but independently testable

### Within Each User Story

- Integration tests MUST be written and FAIL before implementation
- DDLParser before DDLTranslator
- Type/Constraint translators before DDLTranslator integration
- MigrationExecutor after DDLTranslator is functional
- Integration tests verify end-to-end behavior

### Parallel Opportunities

- All Setup tasks marked [P] can run in parallel
- All Foundational tasks marked [P] can run in parallel (within Phase 2)
- Once Foundational phase completes, all user stories can start in parallel (if team capacity allows)
- All integration tests for a user story marked [P] can run in parallel
- Cross-cutting enhancements in Phase 7 can proceed in parallel
- Unit tests in Phase 8 can all run in parallel
- Documentation tasks in Phase 9 can run in parallel

---

## Parallel Example: User Story 1

```bash
# Launch all integration tests for User Story 1 together:
Task: "Integration test: CREATE TABLE with reserved word columns"
Task: "Integration test: CREATE TABLE with PostgreSQL types"
Task: "Integration test: Migration journal tracking"

# Launch foundational components in parallel:
Task: "Create DDLParser class skeleton"
Task: "Create TypeTranslator class"
Task: "Create DDLTranslator class"
```

---

## Implementation Strategy

### MVP First (User Stories 1 & 2 Only - P1 Priority)

1. Complete Phase 1: Setup
2. Complete Phase 2: Foundational (CRITICAL - blocks all stories)
3. Complete Phase 3: User Story 1 (Automatic Schema Sync)
4. Complete Phase 4: User Story 2 (Type Mapping)
5. **STOP and VALIDATE**: Test US1+US2 independently with real Drizzle migrations
6. Deploy/demo if ready - this delivers core value for sim.ai project

**Why this is MVP**: US1+US2 eliminate manual table reconstruction scripts and enable automatic Drizzle migration execution, which is the primary goal stated in the spec.

### Incremental Delivery

1. Complete Setup + Foundational → Foundation ready
2. Add User Story 1 → Test independently → Delivers basic CREATE TABLE (partial value)
3. Add User Story 2 → Test independently → Delivers full type support (MVP complete!)
4. Add User Story 3 → Test independently → Delivers index support (performance benefit)
5. Add User Story 4 → Test independently → Delivers ALTER TABLE support (schema evolution)
6. Add Cross-Cutting → Polish all stories
7. Add CLI → Enable command-line usage
8. Add Documentation → Complete feature

Each story adds value without breaking previous stories.

### Parallel Team Strategy

With multiple developers:

1. Team completes Setup + Foundational together
2. Once Foundational is done:
   - Developer A: User Story 1 (CREATE TABLE foundation)
   - Developer B: User Story 2 (Type mapping extensions)
   - Developer C: User Story 3 (Index support)
   - Developer D: User Story 4 (ALTER TABLE support)
3. Stories complete and integrate independently
4. All developers: Cross-cutting enhancements in Phase 7

---

## Testing Strategy

### Integration Test Coverage (Per User Story)

Each user story MUST have independent integration tests that verify:
1. DDL translation correctness (PostgreSQL → IRIS SQL)
2. End-to-end execution via MigrationExecutor
3. Database state after migration (tables/columns/indexes created)
4. Error handling for unsupported features

### Unit Test Coverage (Phase 8)

- DDLParser: Parsing accuracy for all DDL statement types
- TypeTranslator: All type mappings, precision validation
- ConstraintTranslator: All constraint types (PK, FK, UNIQUE, CHECK)
- ReservedWordChecker: All IRIS reserved words, quoting logic
- DDLTranslator: Statement translation, error generation

### Manual Validation

- Run actual `drizzle-kit generate` against sim.ai schema
- Execute generated migrations via MigrationExecutor
- Verify tables match expected schema
- Perform CRUD operations to validate type semantics

---

## Success Criteria

### From Specification

- ✅ **SC-001**: 100% of CREATE TABLE statements using supported DDL execute without manual modification
- ✅ **SC-002**: Data inserted into Drizzle-migrated tables queries correctly with no type coercion errors
- ✅ **SC-003**: `__drizzle_migrations` journal accurately reflects migration status
- ✅ **SC-004**: Unsupported DDL errors return actionable messages within 100ms
- ✅ **SC-005**: Schema synchronization for 10-50 DDL statements completes within 5 seconds
- ✅ **SC-006**: Standard CRUD operations work on all migrated tables
- ✅ **SC-007**: 90% of common Drizzle patterns execute successfully

### Feature Complete Checklist

- [ ] All P1 user stories (US1, US2) functional
- [ ] All P2 user stories (US3, US4) functional
- [ ] All integration tests passing
- [ ] All unit tests passing (80%+ coverage)
- [ ] CLI functional (--dry-run, --status, --json modes)
- [ ] quickstart.md validated against actual implementation
- [ ] No ruff/black violations
- [ ] CHANGELOG updated
- [ ] README updated with feature overview

---

## Notes

- [P] tasks = different files, no dependencies
- [Story] label maps task to specific user story for traceability
- Each user story should be independently completable and testable
- Verify integration tests fail before implementing
- Commit after each task or logical group
- Stop at any checkpoint to validate story independently
- Avoid: vague tasks, same file conflicts, cross-story dependencies that break independence
- MVP = US1 + US2 (delivers core value: automatic Drizzle migration execution)

# Tasks: PostgreSQL-Compatible SQL Normalization

**Feature**: 021-postgresql-compatible-sql
**Input**: Design documents from `/Users/tdyar/ws/iris-pgwire/specs/021-postgresql-compatible-sql/`
**Prerequisites**: plan.md ✅, research.md ✅, data-model.md ✅, contracts/ ✅, quickstart.md ✅

## Execution Flow (main)
```
1. Load plan.md from feature directory ✅
   → Tech stack: Python 3.11+, asyncio, structlog, intersystems-irispython, re (regex)
   → Structure: Single project, new sql_translator/ module
2. Load optional design documents: ✅
   → data-model.md: 4 entities (SQLQuery, Identifier, DATELiteral, ExecutionContext)
   → contracts/: sql_translator_interface.py (3 interfaces + 5 contract tests)
   → research.md: PgDog proxy patterns, regex-based parsing, < 5ms SLA
3. Generate tasks by category: ✅
   → Setup: Project structure, module initialization
   → Tests: Contract tests (MUST fail initially), integration tests
   → Core: Translator, identifier normalizer, DATE translator
   → Integration: All 3 execution paths (direct, vector, external)
   → Polish: Performance validation, E2E tests, documentation
4. Apply task rules: ✅
   → Different files = mark [P] for parallel
   → Same file = sequential (no [P])
   → Tests before implementation (TDD)
5. Number tasks sequentially (T001-T033) ✅
6. Generate dependency graph ✅
7. Create parallel execution examples ✅
8. Validate task completeness: ✅
   → All contracts have tests? YES
   → All entities have models? YES
   → All endpoints implemented? N/A (not a REST API)
9. Return: SUCCESS (tasks ready for execution) ✅
```

## Format: `[ID] [P?] Description`
- **[P]**: Can run in parallel (different files, no dependencies)
- Include exact file paths in descriptions

## Path Conventions
**Single project structure** (from plan.md):
```
src/iris_pgwire/
├── sql_translator/            # NEW module
│   ├── __init__.py
│   ├── translator.py
│   ├── identifier_normalizer.py
│   ├── date_translator.py
│   └── performance_monitor.py  # Reuse existing
├── iris_executor.py           # MODIFIED (2 functions)
└── vector_optimizer.py        # MODIFIED (1 function)

tests/
├── contract/
│   └── test_sql_translator_contract.py
├── integration/
│   ├── test_sql_file_loading.sh  # EXISTING
│   └── test_sql_normalization_e2e.sh  # NEW
└── unit/
    ├── test_identifier_normalizer.py
    ├── test_date_translator.py
    └── test_sql_translator.py
```

## Phase 3.1: Setup (2 tasks)

- [ ] **T001** Create `src/iris_pgwire/sql_translator/` module directory structure
  - **Files**: Create `src/iris_pgwire/sql_translator/__init__.py` (empty initially)
  - **Validation**: Directory exists and is importable as `iris_pgwire.sql_translator`
  - **Blocked by**: None (first task)

- [ ] **T002** Create test directory structure for SQL normalization tests
  - **Files**:
    - Create `tests/contract/` directory (if not exists)
    - Create `tests/unit/` directory (if not exists)
  - **Validation**: Directories exist and are Python-importable
  - **Blocked by**: None (parallel with T001)

## Phase 3.2: Tests First (TDD) ⚠️ MUST COMPLETE BEFORE 3.3
**CRITICAL: These tests MUST be written and MUST FAIL before ANY implementation**

- [ ] **T003 [P]** Write contract test for `SQLTranslatorInterface.normalize_sql()`
  - **File**: `tests/contract/test_sql_translator_contract.py`
  - **Contract**: `specs/021-postgresql-compatible-sql/contracts/sql_translator_interface.py`
  - **Test Cases**:
    1. `test_normalize_unquoted_identifier` - Verify `FirstName` → `FIRSTNAME`
    2. `test_preserve_quoted_identifier` - Verify `"FirstName"` → `"FirstName"`
    3. `test_translate_date_literal` - Verify `'1985-03-15'` → `TO_DATE('1985-03-15', 'YYYY-MM-DD')`
    4. `test_performance_sla` - Generate SQL with 50 identifiers, assert normalization < 5ms
    5. `test_idempotence` - Verify `normalize(normalize(sql)) == normalize(sql)`
  - **Expected**: All tests MUST FAIL (module not implemented yet)
  - **Blocked by**: T001, T002

- [ ] **T004 [P]** Write unit tests for `IdentifierNormalizer`
  - **File**: `tests/unit/test_identifier_normalizer.py`
  - **Test Cases**:
    1. `test_unquoted_identifier_to_uppercase` - `FirstName` → `FIRSTNAME`
    2. `test_quoted_identifier_preserved` - `"FirstName"` → `"FirstName"`
    3. `test_schema_qualified_identifiers` - `myschema.mytable` → `MYSCHEMA.MYTABLE`
    4. `test_mixed_quoted_unquoted` - `SELECT "CamelCase", LastName FROM Patients`
    5. `test_is_quoted_method` - Verify `is_quoted('"Foo"')` returns True
  - **Expected**: All tests MUST FAIL (class not implemented yet)
  - **Blocked by**: T001, T002

- [ ] **T005 [P]** Write unit tests for `DATETranslator`
  - **File**: `tests/unit/test_date_translator.py`
  - **Test Cases**:
    1. `test_translate_iso8601_date` - `'1985-03-15'` → `TO_DATE('1985-03-15', 'YYYY-MM-DD')`
    2. `test_date_in_insert_values` - Detect DATE in INSERT clause
    3. `test_date_in_where_clause` - Detect DATE in WHERE clause
    4. `test_skip_non_date_strings` - Do NOT translate `'Born 1985-03-15 in...'`
    5. `test_skip_comments` - Do NOT translate `-- '2024-01-01'`
    6. `test_is_valid_date_literal` - Verify regex validation works
  - **Expected**: All tests MUST FAIL (class not implemented yet)
  - **Blocked by**: T001, T002

- [ ] **T006 [P]** Write unit tests for `SQLTranslator` main class
  - **File**: `tests/unit/test_sql_translator.py`
  - **Test Cases**:
    1. `test_normalize_sql_combines_both` - Verify identifiers + DATEs normalized
    2. `test_execution_path_parameter` - Test `execution_path="direct|vector|external"`
    3. `test_get_normalization_metrics` - Verify metrics tracking works
    4. `test_malformed_sql_raises_valueerror` - Error handling for bad SQL
    5. `test_empty_sql_handling` - Edge case validation
  - **Expected**: All tests MUST FAIL (class not implemented yet)
  - **Blocked by**: T001, T002

## Phase 3.3: Core Implementation (ONLY after tests are failing)

- [ ] **T007 [P]** Implement `IdentifierNormalizer` class
  - **File**: `src/iris_pgwire/sql_translator/identifier_normalizer.py`
  - **Interface**: `IdentifierNormalizerInterface` from contract
  - **Methods**:
    - `normalize(sql: str) -> Tuple[str, int]` - Main normalization logic
    - `is_quoted(identifier: str) -> bool` - Quote detection
  - **Implementation**:
    - Use regex to find all identifiers (table names, column names, aliases)
    - Detect quoted identifiers via `"..."` delimiters
    - Convert unquoted identifiers to UPPERCASE
    - Preserve quoted identifier case exactly
    - Return (normalized_sql, identifier_count)
  - **Goal**: Make T004 tests pass
  - **Blocked by**: T003, T004, T005, T006 (tests MUST fail first)

- [ ] **T008 [P]** Implement `DATETranslator` class
  - **File**: `src/iris_pgwire/sql_translator/date_translator.py`
  - **Interface**: `DATETranslatorInterface` from contract
  - **Methods**:
    - `translate(sql: str) -> Tuple[str, int]` - Main translation logic
    - `is_valid_date_literal(literal: str) -> bool` - Validation
  - **Implementation**:
    - Use regex pattern: `'(\d{4}-\d{2}-\d{2})'` (ISO-8601 format)
    - Replace with: `TO_DATE('$1', 'YYYY-MM-DD')`
    - Skip comments (lines starting with `--`)
    - Skip partial strings (DATE not entire literal)
    - Return (translated_sql, date_literal_count)
  - **Goal**: Make T005 tests pass
  - **Blocked by**: T003, T004, T005, T006 (tests MUST fail first)

- [ ] **T009** Implement `SQLTranslator` main class
  - **File**: `src/iris_pgwire/sql_translator/translator.py`
  - **Interface**: `SQLTranslatorInterface` from contract
  - **Dependencies**: Import `IdentifierNormalizer` and `DATETranslator`
  - **Methods**:
    - `__init__(self)` - Initialize normalizer and translator components
    - `normalize_sql(sql: str, execution_path: str) -> str` - Main entry point
    - `normalize_identifiers(sql: str) -> str` - Delegate to IdentifierNormalizer
    - `translate_dates(sql: str) -> str` - Delegate to DATETranslator
    - `get_normalization_metrics(self) -> dict` - Return performance metrics
  - **Implementation**:
    - Track normalization start/end time (use `time.perf_counter()`)
    - Apply identifier normalization FIRST
    - Apply DATE translation SECOND
    - Log warning if normalization exceeds 5ms SLA
    - Return normalized SQL ready for IRIS execution
  - **Goal**: Make T003 and T006 tests pass
  - **Blocked by**: T007, T008 (needs components implemented)

- [ ] **T010** Export public API from `sql_translator` module
  - **File**: `src/iris_pgwire/sql_translator/__init__.py`
  - **Exports**:
    ```python
    from .translator import SQLTranslator
    from .identifier_normalizer import IdentifierNormalizer
    from .date_translator import DATETranslator

    __all__ = ['SQLTranslator', 'IdentifierNormalizer', 'DATETranslator']
    ```
  - **Validation**: `from iris_pgwire.sql_translator import SQLTranslator` works
  - **Blocked by**: T009

## Phase 3.4: Integration (All 3 execution paths)

- [ ] **T011** Integrate normalization into `iris_executor.py::_execute_embedded_async()`
  - **File**: `src/iris_pgwire/iris_executor.py` (MODIFY existing)
  - **Function**: `_execute_embedded_async(sql: str, params: dict, session_id: str) -> ResultSet`
  - **Changes**:
    1. Import: `from .sql_translator import SQLTranslator`
    2. Before `iris.sql.exec(sql)`, add:
       ```python
       translator = SQLTranslator()
       normalized_sql = translator.normalize_sql(sql, execution_path="direct")
       ```
    3. Execute `normalized_sql` instead of `sql`
    4. Log normalization metrics via structlog
  - **Validation**: Direct execution path now normalizes SQL
  - **Blocked by**: T010

- [ ] **T012** Integrate normalization into `iris_executor.py::_execute_external_async()`
  - **File**: `src/iris_pgwire/iris_executor.py` (MODIFY existing)
  - **Function**: `_execute_external_async(sql: str, params: dict, session_id: str) -> ResultSet`
  - **Changes**:
    1. Import: `from .sql_translator import SQLTranslator`
    2. Before `cursor.execute(sql, params)`, add:
       ```python
       translator = SQLTranslator()
       normalized_sql = translator.normalize_sql(sql, execution_path="external")
       ```
    3. Execute `normalized_sql` instead of `sql`
    4. Log normalization metrics via structlog
  - **Validation**: External connection path now normalizes SQL
  - **Blocked by**: T011 (same file - sequential)

- [ ] **T013** Integrate normalization into `vector_optimizer.py::optimize_vector_query()`
  - **File**: `src/iris_pgwire/vector_optimizer.py` (MODIFY existing)
  - **Function**: `optimize_vector_query(sql: str, params: dict) -> Tuple[str, dict]`
  - **Changes**:
    1. Import: `from .sql_translator import SQLTranslator`
    2. **BEFORE** vector optimization logic, add:
       ```python
       translator = SQLTranslator()
       normalized_sql = translator.normalize_sql(sql, execution_path="vector")
       ```
    3. Apply vector optimization to `normalized_sql` (not original `sql`)
    4. Validate FR-012: Normalization occurs BEFORE optimization
  - **Validation**: Vector-optimized path normalizes SQL correctly
  - **Blocked by**: T012

## Phase 3.5: E2E Testing & Validation

- [ ] **T014 [P]** Create E2E integration test script
  - **File**: `tests/integration/test_sql_normalization_e2e.sh`
  - **Test Scenarios**:
    1. Mixed-case identifier normalization: `INSERT INTO Patients (FirstName, LastName)`
    2. Quoted identifier preservation: `CREATE TABLE "MixedCase" ("CamelCase" INT)`
    3. DATE literal translation: `WHERE DateOfBirth = '1985-03-15'`
    4. Mixed quoted/unquoted: `SELECT "CamelCase", LastName FROM "MixedCase"`
  - **Validation**: All scenarios execute successfully via psql client
  - **Blocked by**: T013 (implementation complete)

- [ ] **T015** Execute quickstart.md Steps 1-5 (Core validation)
  - **Steps** (from quickstart.md):
    1. Drop existing Patients table
    2. Create Patients table with mixed-case identifiers
    3. Load 250-patient dataset via `psql -f patients-data.sql` (THE CRITICAL TEST)
    4. Verify patient count = 250
    5. Verify DATE values loaded correctly for first 3 patients
  - **Expected**: All 250 records load without errors
  - **Blocked by**: T014

- [ ] **T016** Execute quickstart.md Steps 6-8 (Edge cases)
  - **Steps**:
    6. Test quoted identifier preservation: `CREATE TABLE "MixedCase"`
    7. Test mixed quoted/unquoted identifiers: `SELECT CamelCase FROM "MixedCase"`
    8. Test DATE in WHERE clause: `WHERE DateOfBirth = '1985-03-15'`
  - **Expected**: All edge cases work correctly
  - **Blocked by**: T015

- [ ] **T017 [P]** Verify normalization works with existing integration test
  - **File**: `tests/integration/test_sql_file_loading.sh` (EXISTING - run only)
  - **Action**: Re-run existing integration test to ensure normalization doesn't break it
  - **Expected**: Integration test passes (backward compatibility maintained)
  - **Blocked by**: T013

## Phase 3.6: Performance Validation (Constitutional Compliance)

- [ ] **T018** Benchmark normalization overhead for 50 identifiers
  - **Test**: Generate SQL with 50 identifier references (see quickstart.md Step 9)
  - **SQL**:
    ```sql
    SELECT
        PatientID, FirstName, LastName, DateOfBirth, Gender, Status, AdmissionDate, DischargeDate,
        PatientID as id1, FirstName as fn1, LastName as ln1,
        ... (repeated 10 times for 50 total identifiers)
    FROM Patients LIMIT 1
    ```
  - **Measurement**: Check PGWire logs for `normalization_time_ms`
  - **Expected**: `normalization_time_ms < 5.0` (constitutional requirement)
  - **Blocked by**: T016

- [ ] **T019** Validate total execution time increase < 10%
  - **Baseline**: Execute simple queries WITHOUT normalization (disable feature)
  - **Normalized**: Execute same queries WITH normalization (feature enabled)
  - **Measurement**: Compare total execution times
  - **Expected**: Normalized time < 110% of baseline time
  - **Blocked by**: T018

- [ ] **T020** Stress test with 250-patient dataset (2000 identifiers)
  - **Test**: Load full patients-data.sql (250 rows × 8 columns = 2000 identifier references)
  - **Measurement**: Check normalization time for entire file load
  - **Expected**: Average normalization time per query < 5ms
  - **Blocked by**: T019

## Phase 3.7: Edge Cases & Error Handling

- [ ] **T021 [P]** Test schema-qualified identifiers
  - **SQL**: `SELECT myschema.mytable.column FROM myschema.mytable`
  - **Expected**: `SELECT MYSCHEMA.MYTABLE.COLUMN FROM MYSCHEMA.MYTABLE`
  - **Validation**: Schema-qualified identifiers normalized correctly
  - **Blocked by**: T016

- [ ] **T022 [P]** Test DATE in prepared statements
  - **SQL**: `WHERE DateOfBirth = $1` (with parameter `'1985-03-15'`)
  - **Expected**: Parameter value NOT translated (only literal DATEs)
  - **Validation**: Parameterized queries work correctly
  - **Blocked by**: T016

- [ ] **T023 [P]** Test complex SQL (JOINs, subqueries, CTEs)
  - **SQL**:
    ```sql
    WITH PatientStats AS (
        SELECT PatientID, COUNT(*) as VisitCount
        FROM Patients p
        JOIN LabResults l ON p.PatientID = l.PatientID
        WHERE p.DateOfBirth > '1980-01-01'
        GROUP BY PatientID
    )
    SELECT * FROM PatientStats
    ```
  - **Expected**: All identifiers and DATEs normalized correctly in complex query
  - **Blocked by**: T016

- [ ] **T024** Test malformed SQL error handling
  - **SQL**: `SELEC FROM` (invalid syntax)
  - **Expected**: Normalization skips malformed SQL, propagates error to client
  - **Error**: PostgreSQL syntax error (not normalization error)
  - **Blocked by**: T023

- [ ] **T025** Test empty/NULL SQL handling
  - **SQL**: Empty string, NULL, whitespace-only
  - **Expected**: Graceful handling, no crashes
  - **Validation**: Edge case robustness
  - **Blocked by**: T024

## Phase 3.8: Vector Path Validation (Constitutional Principle VI)

- [ ] **T026** Verify vector queries work with normalization
  - **SQL**:
    ```sql
    SELECT PatientID, VECTOR_COSINE(embedding, TO_VECTOR('[0.1,0.2,...]'))
    FROM VectorData
    ORDER BY VECTOR_COSINE(embedding, TO_VECTOR('[0.1,0.2,...]')) DESC
    LIMIT 5
    ```
  - **Expected**: Identifiers normalized, then vector optimization applied
  - **Validation**: FR-012 satisfied (normalization BEFORE optimization)
  - **Blocked by**: T023

- [ ] **T027** Measure vector query performance with normalization
  - **Measurement**: Compare vector query latency with/without normalization
  - **Expected**: Performance degradation < 5ms (within constitutional SLA)
  - **Blocked by**: T026

## Phase 3.9: Polish

- [ ] **T028 [P]** Add performance logging to `SQLTranslator`
  - **File**: `src/iris_pgwire/sql_translator/translator.py` (MODIFY)
  - **Changes**:
    - Use `structlog` to log normalization metrics
    - Log SLA violations (> 5ms) as WARNING level
    - Log identifier/DATE counts as INFO level
  - **Validation**: Logs show normalization metrics
  - **Blocked by**: T020

- [ ] **T029 [P]** Document SQL normalization in CLAUDE.md
  - **File**: `/Users/tdyar/ws/iris-pgwire/CLAUDE.md` (UPDATE)
  - **Content**: Add section on SQL normalization feature:
    - Integration points (all 3 execution paths)
    - Normalization rules (identifiers, DATEs)
    - Performance requirements
    - Critical test case (250-patient dataset)
  - **Validation**: Documentation complete and accurate
  - **Blocked by**: T020

- [ ] **T030** Execute quickstart.md Step 9 (Performance validation)
  - **Step**: Performance validation with 50 identifiers
  - **Expected**: `normalization_time_ms < 5.0` logged
  - **Blocked by**: T028

- [ ] **T031** Execute quickstart.md Step 10 (Cleanup)
  - **Step**: Drop test tables
  - **Expected**: Clean state for future tests
  - **Blocked by**: T030

- [ ] **T032 [P]** Review code for duplication and refactoring opportunities
  - **Files**: All `sql_translator/` module files
  - **Actions**:
    - Check for duplicated regex patterns
    - Ensure consistent error handling
    - Verify logging consistency
  - **Validation**: Code quality improved
  - **Blocked by**: T028, T029

- [ ] **T033** Final validation: Run all tests end-to-end
  - **Tests**:
    - Contract tests: `pytest tests/contract/`
    - Unit tests: `pytest tests/unit/`
    - Integration tests: `./tests/integration/test_sql_normalization_e2e.sh`
    - Existing integration: `./tests/integration/test_sql_file_loading.sh`
    - Quickstart validation: Execute all 10 steps
  - **Expected**: All tests pass, all steps succeed
  - **Blocked by**: T031, T032

## Dependencies
```
Setup (T001-T002)
  ↓
Tests (T003-T006) [P] - MUST FAIL
  ↓
Core Implementation (T007-T010)
  T007 [P], T008 [P] → T009 → T010
  ↓
Integration (T011-T013)
  T011 → T012 → T013 (same files - sequential)
  ↓
E2E Testing (T014-T017)
  T014 [P] → T015 → T016
  T017 [P] (independent)
  ↓
Performance (T018-T020)
  T018 → T019 → T020
  ↓
Edge Cases (T021-T025)
  T021 [P], T022 [P], T023 [P] → T024 → T025
  ↓
Vector Validation (T026-T027)
  T026 → T027
  ↓
Polish (T028-T033)
  T028 [P], T029 [P] → T030 → T031 → T032 [P] → T033
```

## Parallel Execution Examples

**Phase 3.2 - Write All Tests in Parallel** (T003-T006):
```bash
# Execute all contract and unit tests together (different files, no dependencies)
T003: "Write contract test for SQLTranslatorInterface"
T004: "Write unit tests for IdentifierNormalizer"
T005: "Write unit tests for DATETranslator"
T006: "Write unit tests for SQLTranslator main class"
```

**Phase 3.3 - Implement Components in Parallel** (T007-T008):
```bash
# Implement IdentifierNormalizer and DATETranslator together
T007: "Implement IdentifierNormalizer class"
T008: "Implement DATETranslator class"
```

**Phase 3.5 - Run Independent Tests in Parallel** (T014, T017):
```bash
# E2E test and existing integration test can run together
T014: "Create E2E integration test script"
T017: "Verify normalization works with existing integration test"
```

**Phase 3.7 - Test Edge Cases in Parallel** (T021-T023):
```bash
# Different test scenarios, no shared resources
T021: "Test schema-qualified identifiers"
T022: "Test DATE in prepared statements"
T023: "Test complex SQL (JOINs, subqueries, CTEs)"
```

**Phase 3.9 - Final Polish in Parallel** (T028-T029, T032):
```bash
# Documentation and logging are independent
T028: "Add performance logging to SQLTranslator"
T029: "Document SQL normalization in CLAUDE.md"
T032: "Review code for duplication and refactoring opportunities"
```

## Notes
- **[P] tasks** = different files, no dependencies, can run in parallel
- **TDD Critical**: T003-T006 MUST fail before T007-T010 implementation
- **Performance SLA**: < 5ms normalization overhead (constitutional requirement)
- **250-Patient Test**: THE critical validation (T015) - all 250 records MUST load
- **3 Execution Paths**: Direct (T011), External (T012), Vector (T013) - all covered
- **Commit after each task** for atomic progress tracking
- **Avoid**: Implementing before tests fail, skipping performance validation

## Task Generation Rules Applied
1. **From Contracts**:
   - `sql_translator_interface.py` → T003 (contract test) [P]
   - `SQLTranslatorInterface` → T006 (main class test) [P]
   - `IdentifierNormalizerInterface` → T004 (component test) [P]
   - `DATETranslatorInterface` → T005 (component test) [P]

2. **From Data Model**:
   - `SQLQuery` entity → T009 (SQLTranslator class)
   - `Identifier` entity → T007 (IdentifierNormalizer class) [P]
   - `DATELiteral` entity → T008 (DATETranslator class) [P]
   - `ExecutionContext` → T011-T013 (3 execution paths)

3. **From Quickstart**:
   - Steps 1-5 → T015 (core validation)
   - Steps 6-8 → T016 (edge cases)
   - Step 9 → T018, T030 (performance validation)
   - Step 10 → T031 (cleanup)
   - 250-patient dataset → T020 (stress test)

4. **Ordering**:
   - Setup (T001-T002) → Tests (T003-T006) → Implementation (T007-T010) → Integration (T011-T013) → Validation (T014-T033)
   - Dependencies block parallel execution (e.g., T011 → T012 same file)

## Validation Checklist
*GATE: Verified before task generation*

- [x] All contracts have corresponding tests (T003-T006)
- [x] All entities have implementation tasks (T007-T009)
- [x] All tests come before implementation (T003-T006 before T007-T010)
- [x] Parallel tasks truly independent (checked file paths)
- [x] Each task specifies exact file path (all tasks include file paths)
- [x] No task modifies same file as another [P] task (verified)

---

**Tasks Status**: ✅ **READY FOR EXECUTION**
**Total Tasks**: 33 (numbered T001-T033)
**Estimated Time**: 2-3 days (TDD approach with comprehensive testing)
**Critical Path**: T001 → T003-T006 (tests fail) → T007-T010 (implementation) → T011-T013 (integration) → T015 (250-patient test)
**Success Criteria**: All tests pass, 250 patient records load successfully, normalization < 5ms

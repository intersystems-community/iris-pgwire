# Implementation Plan: PostgreSQL-Compatible SQL Normalization

**Branch**: `021-postgresql-compatible-sql` | **Date**: 2025-10-08 | **Spec**: [spec.md](./spec.md)
**Input**: Feature specification from `/Users/tdyar/ws/iris-pgwire/specs/021-postgresql-compatible-sql/spec.md`

## Execution Flow (/plan command scope)
```
1. Load feature spec from Input path ✅
2. Fill Technical Context (scan for NEEDS CLARIFICATION) ✅
3. Fill the Constitution Check section ✅
4. Evaluate Constitution Check section ✅
5. Execute Phase 0 → research.md ✅
6. Execute Phase 1 → contracts, data-model.md, quickstart.md, CLAUDE.md ✅
7. Re-evaluate Constitution Check section ✅
8. Plan Phase 2 → Describe task generation approach ✅
9. STOP - Ready for /tasks command ✅
```

## Summary

**Primary Requirement**: Enable PostgreSQL clients to execute SQL against IRIS without modification by normalizing identifier case (unquoted → UPPERCASE) and DATE literal format (`'YYYY-MM-DD'` → `TO_DATE()` translation).

**Technical Approach**: Protocol-layer SQL normalization following industry best practices (PgDog proxy patterns) with < 5ms overhead, covering all three execution paths (direct, vector-optimized, external).

**Success Criteria**: Load 250-patient healthcare dataset (`patients-data.sql`) via standard `psql -f` command without SQL modifications.

## Technical Context

**Language/Version**: Python 3.11+
**Primary Dependencies**:
- `asyncio` (async server framework)
- `structlog` (structured logging)
- `intersystems-irispython>=5.1.2` (IRIS embedded Python)
- `re` (regex for SQL parsing)

**Storage**: InterSystems IRIS database via embedded Python (`iris.sql.exec()`)
**Testing**:
- E2E: `psql` client integration tests
- Unit: pytest for SQL normalization logic
- Integration: `test_sql_file_loading.sh` for 250-patient dataset

**Target Platform**: Linux/macOS server (Docker container with IRIS embedded Python via `irispython` command)
**Project Type**: Single project (asyncio server)
**Performance Goals**:
- Normalization overhead < 5ms for 50 identifier references
- Total execution time < 10% baseline increase
- Translation SLA: 5ms (constitutional requirement)

**Constraints**:
- Must preserve PostgreSQL wire protocol compatibility
- Must not modify IRIS backend
- Must work across all 3 execution paths (direct, vector-optimized, external)
- Must handle quoted identifiers (preserve case) vs unquoted (normalize to UPPERCASE)

**Scale/Scope**:
- Real-world validation: 250-patient healthcare dataset
- Query complexity: Multi-column INSERTs with DATE literals
- Identifier count: Up to 50 identifiers per query
- Vector queries: Must work with vector optimization layer

## Constitution Check
*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

### Protocol Fidelity (Principle I)
✅ **PASS**: SQL normalization at protocol layer maintains PostgreSQL compatibility
- Quoted identifiers preserved (PostgreSQL standard)
- Unquoted identifiers normalized to UPPERCASE (IRIS requirement)
- DATE literal translation transparent to clients

### Test-First Development (Principle II)
✅ **PASS**: Real client testing with psql and integration tests
- E2E test: `patients-data.sql` (250 records) via `psql -f`
- Integration test: `test_sql_file_loading.sh` validates complete workflow
- No mocks - real IRIS database and real PostgreSQL clients

### Phased Implementation (Principle III)
✅ **PASS**: Feature builds on existing P1 (Simple Query) foundation
- P0-P1 already complete (handshake, simple query execution)
- This feature enhances P1 with SQL normalization
- No cross-phase dependencies

### IRIS Integration (Principle IV)
✅ **PASS**: Uses established embedded Python patterns
- Normalization applied in `iris_executor.py::_execute_embedded_async()` (existing)
- Vector optimization path coverage: `vector_optimizer.py::optimize_vector_query()`
- External connection path coverage: `iris_executor.py::_execute_external_async()`
- Async threading with `asyncio.to_thread()` preserved

### Production Readiness (Principle V)
✅ **PASS**: Includes monitoring and performance tracking
- Performance monitoring via existing `performance_monitor` infrastructure
- Structured logging via `structlog` for normalization operations
- Error handling for malformed SQL and edge cases

### Vector Performance Requirements (Principle VI)
✅ **PASS**: Normalization compatible with vector optimization
- FR-010: Explicit requirement for vector-optimized execution path
- Normalization occurs BEFORE vector optimization (FR-012)
- No impact on HNSW index performance (< 5ms translation overhead)
- Vector datatype matching preserved (DOUBLE/FLOAT detection)

### Performance Standards
✅ **PASS**: Constitutional 5ms translation SLA maintained
- FR-013: Normalization overhead < 5ms for 50 identifiers
- FR-014: Total execution time < 10% baseline increase
- Validated against industry benchmarks (PgDog proxy)

**Constitution Check Result**: ✅ **ALL CHECKS PASS** - No violations, proceed to implementation

## Project Structure

### Documentation (this feature)
```
specs/021-postgresql-compatible-sql/
├── spec.md              # Feature specification ✅
├── plan.md              # This file (/plan command output)
├── research.md          # Phase 0 output (/plan command)
├── data-model.md        # Phase 1 output (/plan command)
├── quickstart.md        # Phase 1 output (/plan command)
├── contracts/           # Phase 1 output (/plan command)
│   └── sql_translator_interface.py
└── tasks.md             # Phase 2 output (/tasks command - NOT created by /plan)
```

### Source Code (repository root)
```
src/iris_pgwire/
├── protocol.py                # PGWire protocol handler (existing)
├── iris_executor.py           # IRIS SQL execution (existing - MODIFIED)
│   ├── _execute_embedded_async()   # Direct path normalization
│   └── _execute_external_async()   # External path normalization
├── vector_optimizer.py        # Vector query optimization (existing - MODIFIED)
│   └── optimize_vector_query()     # Vector path normalization
├── sql_translator/            # NEW: SQL normalization module
│   ├── __init__.py
│   ├── translator.py          # Main translation logic
│   ├── identifier_normalizer.py    # Identifier case normalization
│   ├── date_translator.py          # DATE literal translation
│   └── performance_monitor.py      # Performance tracking (existing - reused)
└── types.py                   # Type system (existing)

tests/
├── contract/                  # Contract tests (NEW)
│   └── test_sql_translator_contract.py
├── integration/               # Integration tests (existing)
│   ├── test_sql_file_loading.sh   # 250-patient dataset test (existing)
│   └── test_sql_normalization_e2e.sh  # NEW: Normalization E2E test
└── unit/                      # Unit tests (NEW)
    ├── test_identifier_normalizer.py
    ├── test_date_translator.py
    └── test_sql_translator.py
```

**Structure Decision**: Single project structure. SQL normalization is a protocol-layer enhancement integrated into existing `iris_executor.py` and `vector_optimizer.py` execution paths. New `sql_translator/` module provides reusable normalization components.

## Phase 0: Outline & Research

**Research Completed** (from spec.md Research Validation section):

### 1. PostgreSQL Identifier Case Sensitivity
**Decision**: Normalize unquoted identifiers to UPPERCASE, preserve quoted identifiers
**Rationale**:
- PostgreSQL: Unquoted → lowercase (SQL standard)
- IRIS: Unquoted → UPPERCASE (Oracle-like)
- Quoted identifiers preserve case in both systems

**Alternatives Considered**:
- ❌ Modify IRIS to accept lowercase: Not feasible, requires IRIS core changes
- ❌ Force clients to use quoted identifiers: Breaks PostgreSQL compatibility
- ✅ Protocol-layer normalization: Industry best practice (PgDog proxy)

### 2. DATE Literal Translation
**Decision**: Translate `'YYYY-MM-DD'` to `TO_DATE('YYYY-MM-DD', 'YYYY-MM-DD')`
**Rationale**:
- PostgreSQL clients send ISO-8601 format
- IRIS requires `TO_DATE()` function or internal format
- Regex-based pattern matching with context-awareness

**Alternatives Considered**:
- ❌ Modify IRIS to accept ISO-8601: Not feasible
- ❌ Require clients to use `TO_DATE()`: Breaks PostgreSQL compatibility
- ✅ Automatic translation: Transparent to clients

### 3. SQL Parsing Strategy
**Decision**: Regex-based parsing with quote-awareness
**Rationale**:
- Handle quoted vs unquoted identifiers correctly
- Detect DATE literals in INSERT, UPDATE, WHERE clauses
- Avoid false positives (string literals, comments)

**Alternatives Considered**:
- ❌ Full SQL parser (sqlparse): Overkill, performance overhead
- ❌ Token-based parsing: Too complex for this use case
- ✅ Regex with context-awareness: Proven in PgDog proxy

### 4. Performance Validation
**Decision**: < 5ms overhead target, validated via benchmarks
**Rationale**:
- Constitutional requirement: 5ms translation SLA
- Industry benchmarks: PgDog proxy achieves < 5ms
- 50 identifier references = realistic worst case

**Alternatives Considered**:
- ❌ No performance target: Violates constitution
- ❌ 10ms target: Too permissive
- ✅ 5ms target: Aligned with constitutional standards

### 5. Integration Points
**Decision**: All 3 execution paths (direct, vector-optimized, external)
**Rationale**:
- FR-009, FR-010, FR-011 explicit requirements
- User feedback: "make sure it works with both the 'direct' and 'vector optimized' and any other paths to execution"
- Normalization BEFORE optimization (FR-012)

**Alternatives Considered**:
- ❌ Only direct path: Misses vector queries
- ❌ Only vector path: Misses simple queries
- ✅ All paths: Complete coverage

**Output**: research.md (generated next)

## Phase 1: Design & Contracts

### Data Model

**Key Entities** (from spec.md):
1. **SQL Query**: Complete SQL statement requiring normalization
2. **Identifier**: Table name, column name, or alias (quoted/unquoted)
3. **DATE Literal**: String literal in format `'YYYY-MM-DD'`
4. **Execution Context**: Tracks execution path (direct/vector/external)

**State Transitions**:
```
SQL Query → Parse Identifiers → Normalize Identifiers → Translate DATEs → Normalized SQL → IRIS Execution
```

**Validation Rules**:
- Quoted identifiers: Preserve exact case
- Unquoted identifiers: Convert to UPPERCASE
- DATE literals: Must match `'YYYY-MM-DD'` regex
- Performance: Normalization < 5ms for 50 identifiers

### API Contracts

**Contract**: `SQLTranslator` interface

```python
# contracts/sql_translator_interface.py
class SQLTranslator:
    """
    Contract for SQL normalization layer.

    Constitutional Requirements:
    - Normalization overhead < 5ms for 50 identifiers
    - Total execution time < 10% baseline increase
    - Preserve quoted identifier case, normalize unquoted to UPPERCASE
    - Translate DATE literals from 'YYYY-MM-DD' to TO_DATE(...)
    """

    def normalize_sql(self, sql: str, execution_path: str) -> str:
        """
        Normalize SQL for IRIS compatibility.

        Args:
            sql: Original SQL from PostgreSQL client
            execution_path: "direct"|"vector"|"external"

        Returns:
            Normalized SQL ready for IRIS execution

        Raises:
            ValueError: If SQL is malformed or unparseable
        """
        pass

    def normalize_identifiers(self, sql: str) -> str:
        """Normalize identifiers: unquoted → UPPERCASE, quoted → preserve"""
        pass

    def translate_dates(self, sql: str) -> str:
        """Translate DATE literals: 'YYYY-MM-DD' → TO_DATE(...)"""
        pass
```

### Contract Tests

**Test Scenarios** (from spec.md acceptance scenarios):
1. Mixed-case identifier normalization
2. Quoted identifier preservation
3. DATE literal translation
4. 250-patient dataset E2E test
5. Vector query normalization + optimization

**Test Files** (generated in Phase 1):
- `tests/contract/test_sql_translator_contract.py`
- `tests/integration/test_sql_normalization_e2e.sh`
- `tests/unit/test_identifier_normalizer.py`
- `tests/unit/test_date_translator.py`

### Quickstart Test

**Quickstart Validation** (from `quickstart.md`):
```bash
# Step 1: Drop and recreate Patients table
psql -h localhost -p 5432 -U test_user -d USER -c "
DROP TABLE IF EXISTS Patients;
CREATE TABLE Patients (
    PatientID INT PRIMARY KEY,
    FirstName VARCHAR(50) NOT NULL,
    LastName VARCHAR(50) NOT NULL,
    DateOfBirth DATE NOT NULL,
    Gender VARCHAR(10) NOT NULL,
    Status VARCHAR(20) NOT NULL,
    AdmissionDate DATE NOT NULL,
    DischargeDate DATE
);"

# Step 2: Load 250-patient dataset (THE CRITICAL TEST)
psql -h localhost -p 5432 -U test_user -d USER \
    -f examples/superset-iris-healthcare/data/patients-data.sql

# Step 3: Verify count
psql -h localhost -p 5432 -U test_user -d USER -c "SELECT COUNT(*) FROM Patients;"
# Expected: 250

# Step 4: Verify DATE values loaded correctly
psql -h localhost -p 5432 -U test_user -d USER -c "
SELECT PatientID, FirstName, LastName, DateOfBirth
FROM Patients
WHERE PatientID IN (1, 2, 3)
ORDER BY PatientID;"
# Expected: Correct DATE values for first 3 patients
```

### Agent Context Update

**CLAUDE.md Update** (incremental - preserve existing content):
```markdown
## 🔄 SQL Translation REST API (Feature 021)

### Overview

**Feature**: 021-postgresql-compatible-sql
**Status**: Implementation phase
**Scope**: SQL normalization layer for identifier case sensitivity and DATE literal translation

**Problem Solved**: PostgreSQL clients send mixed-case identifiers and ISO-8601 DATE literals that IRIS rejects. This feature translates SQL transparently at the protocol layer.

### Integration Points (ALL execution paths)

1. **Direct Execution** (`iris_executor.py::_execute_embedded_async`):
   ```python
   # Apply normalization BEFORE executing
   from .sql_translator import normalize_sql
   normalized_sql = normalize_sql(sql, execution_path="direct")
   result = iris.sql.exec(normalized_sql)
   ```

2. **Vector Optimized** (`vector_optimizer.py::optimize_vector_query`):
   ```python
   # Normalization BEFORE vector optimization
   from .sql_translator import normalize_sql
   normalized_sql = normalize_sql(sql, execution_path="vector")
   # Then apply vector optimization
   optimized_sql, params = optimize_vector_query(normalized_sql, params)
   ```

3. **External Connection** (`iris_executor.py::_execute_external_async`):
   ```python
   # Same normalization for external connections
   normalized_sql = normalize_sql(sql, execution_path="external")
   cursor.execute(normalized_sql, params)
   ```

### Normalization Rules

**Identifier Normalization**:
- `FirstName` → `FIRSTNAME` (unquoted → UPPERCASE)
- `"FirstName"` → `"FirstName"` (quoted → preserve case)

**DATE Literal Translation**:
- `'1985-03-15'` → `TO_DATE('1985-03-15', 'YYYY-MM-DD')`
- Only in INSERT, UPDATE, WHERE clauses
- Avoid false positives (string literals, comments)

### Performance Requirements (Constitutional)

- Normalization overhead < 5ms for 50 identifier references
- Total execution time < 10% baseline increase
- Translation SLA: 5ms (Principle VI)

### Critical Test Case

**250-Patient Dataset** (`examples/superset-iris-healthcare/data/patients-data.sql`):
- Mixed-case identifiers: `FirstName`, `LastName`, `DateOfBirth`
- DATE literals: `'1985-03-15'`, `'1972-07-22'`, etc.
- Must load via `psql -f` without modification
- Validates complete normalization pipeline

### Recent Changes
- 2025-10-08: Specification and planning complete
- 2025-10-08: Constitutional compliance validated (all checks pass)
- 2025-10-08: Research validation completed (PgDog proxy patterns)
```

**Output**:
- data-model.md ✅
- contracts/sql_translator_interface.py ✅
- quickstart.md ✅
- CLAUDE.md updated ✅
- Failing contract tests ✅

## Phase 2: Task Planning Approach
*This section describes what the /tasks command will do - DO NOT execute during /plan*

**Task Generation Strategy**:
- Load `.specify/templates/tasks-template.md` as base
- Generate tasks from Phase 1 design docs (contracts, data model, quickstart)
- TDD ordering: Tests before implementation
- Constitutional validation: Performance benchmarks

**Task Categories** (estimated 25-30 tasks):

1. **Contract Tests** (3 tasks) [P]:
   - T001: Write `test_sql_translator_contract.py` - MUST fail initially
   - T002: Write `test_identifier_normalizer.py` - MUST fail initially
   - T003: Write `test_date_translator.py` - MUST fail initially

2. **Core Implementation** (5 tasks):
   - T004: Create `sql_translator/translator.py` module
   - T005: Implement `normalize_identifiers()` - make T002 pass
   - T006: Implement `translate_dates()` - make T003 pass
   - T007: Integrate into `iris_executor.py::_execute_embedded_async()`
   - T008: Integrate into `iris_executor.py::_execute_external_async()`

3. **Vector Path Integration** (2 tasks):
   - T009: Integrate normalization into `vector_optimizer.py`
   - T010: Validate normalization BEFORE optimization (FR-012)

4. **E2E Testing** (4 tasks):
   - T011: Create `test_sql_normalization_e2e.sh` integration test
   - T012: Test mixed-case identifier normalization
   - T013: Test quoted identifier preservation
   - T014: Test DATE literal translation

5. **Critical Validation** (3 tasks):
   - T015: Run `test_sql_file_loading.sh` (250-patient dataset)
   - T016: Validate all 250 records load successfully
   - T017: Verify DATE values correct

6. **Performance Validation** (3 tasks):
   - T018: Benchmark normalization overhead (50 identifiers)
   - T019: Validate < 5ms overhead (constitutional requirement)
   - T020: Validate < 10% total execution time increase

7. **Edge Cases** (5 tasks):
   - T021: Test mixed quoted/unquoted identifiers
   - T022: Test DATE in WHERE clauses
   - T023: Test DATE in prepared statements
   - T024: Test complex SQL (JOINs, subqueries, CTEs)
   - T025: Test malformed SQL error handling

**Ordering Strategy**:
- Tests written BEFORE implementation (TDD)
- Contract tests MUST fail initially
- Implementation tasks make tests pass
- E2E tests validate complete workflow
- Performance validation confirms constitutional compliance
- [P] marks indicate parallel execution possibility

**Estimated Output**: 25 numbered, ordered tasks in tasks.md

**IMPORTANT**: This phase is executed by the /tasks command, NOT by /plan

## Phase 3+: Future Implementation
*These phases are beyond the scope of the /plan command*

**Phase 3**: Task execution (/tasks command creates tasks.md)
**Phase 4**: Implementation (execute tasks.md following TDD principles)
**Phase 5**: Validation (run tests, execute quickstart.md, performance validation)

## Complexity Tracking

**No constitutional violations** - complexity tracking not required.

All constitutional principles satisfied:
- ✅ Protocol Fidelity: PostgreSQL compatibility maintained
- ✅ Test-First: Real client testing with psql
- ✅ Phased Implementation: Builds on P1 foundation
- ✅ IRIS Integration: Embedded Python patterns preserved
- ✅ Production Readiness: Monitoring and logging included
- ✅ Vector Performance: Compatible with HNSW optimization
- ✅ Performance Standards: < 5ms translation SLA

## Progress Tracking

**Phase Status**:
- [x] Phase 0: Research complete (/plan command)
- [x] Phase 1: Design complete (/plan command)
- [x] Phase 2: Task planning complete (/plan command - describe approach only)
- [ ] Phase 3: Tasks generated (/tasks command)
- [ ] Phase 4: Implementation complete
- [ ] Phase 5: Validation passed

**Gate Status**:
- [x] Initial Constitution Check: PASS (all principles satisfied)
- [x] Post-Design Constitution Check: PASS (no violations)
- [x] All NEEDS CLARIFICATION resolved (research completed)
- [x] Complexity deviations documented (N/A - no deviations)

---
*Based on Constitution v1.2.4 - See `.specify/memory/constitution.md`*

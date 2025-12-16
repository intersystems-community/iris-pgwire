# Implementation Plan: PostgreSQL Transaction Verb Compatibility

**Branch**: `022-postgresql-transaction-verb` | **Date**: 2025-11-08 | **Spec**: [spec.md](./spec.md)
**Input**: Feature specification from `/specs/022-postgresql-transaction-verb/spec.md`

## Execution Flow (/plan command scope)
```
1. Load feature spec from Input path
   → ✅ COMPLETE: Spec loaded successfully
2. Fill Technical Context (scan for NEEDS CLARIFICATION)
   → ✅ COMPLETE: All technical details known, no clarifications needed
3. Fill the Constitution Check section based on constitution document
   → ✅ COMPLETE: All 7 principles evaluated
4. Evaluate Constitution Check section
   → ✅ PASS: No violations detected
   → ✅ Update Progress Tracking: Initial Constitution Check
5. Execute Phase 0 → research.md
   → ✅ COMPLETE: No unknowns to research (simple translation feature)
6. Execute Phase 1 → contracts, data-model.md, quickstart.md, CLAUDE.md
   → ✅ COMPLETE: All design artifacts generated
7. Re-evaluate Constitution Check section
   → ✅ PASS: Post-Design Constitution Check compliant
   → ✅ Update Progress Tracking: Post-Design Constitution Check
8. Plan Phase 2 → Describe task generation approach (DO NOT create tasks.md)
   → ✅ COMPLETE: Task strategy documented
9. STOP - Ready for /tasks command
```

**IMPORTANT**: The /plan command STOPS at step 8. Phases 2-4 are executed by other commands:
- Phase 2: /tasks command creates tasks.md
- Phase 3-4: Implementation execution (manual or via tools)

## Summary

PostgreSQL clients expect `BEGIN` to start transactions, but IRIS SQL uses `START TRANSACTION`. This feature implements a lightweight protocol-layer translation to enable standard PostgreSQL transaction control syntax. The translator intercepts `BEGIN` commands before SQL normalization (Feature 021) and rewrites them to `START TRANSACTION`, preserving transaction modifiers and handling edge cases. Performance target: <0.1ms translation overhead to maintain the constitutional 5ms query SLA. Implementation integrates with the existing SQL execution pipeline at three points: direct execution, external connection fallback, and vector query optimization path.

## Technical Context

**Language/Version**: Python 3.11 (embedded Python via irispython command)
**Primary Dependencies**: asyncio (protocol server), structlog (logging), pytest (testing), psycopg>=3.1.0 (E2E testing)
**Storage**: N/A (transaction control is ephemeral, no persistent data)
**Testing**: pytest with real PostgreSQL clients (psql, psycopg, SQLAlchemy context managers)
**Target Platform**: Docker container (iris-pgwire-db) running embedded Python inside IRIS process
**Project Type**: Single project (iris-pgwire protocol server)
**Performance Goals**: <0.1ms translation overhead per transaction command, <5ms total query latency (constitutional SLA)
**Constraints**: Must integrate with Feature 021 SQL normalization pipeline, translation must occur BEFORE normalization (FR-010), no additional IRIS round-trips (PR-003)
**Scale/Scope**: Single-file implementation (~100-150 lines), 3 integration points (iris_executor.py, protocol.py optional, sql_translator/), 10 functional requirements, 5 E2E acceptance scenarios

## Constitution Check
*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

**Principle I: Protocol Fidelity**
✅ **PASS**: Feature translates PostgreSQL standard `BEGIN` syntax to IRIS-compatible `START TRANSACTION` without changing PostgreSQL wire protocol message structure. Translation is transparent to clients - maintains protocol compliance.

**Principle II: Test-First Development**
✅ **PASS**: Specification includes TR-001 through TR-005 requiring E2E tests with real psql and psycopg clients. Tests must be written first and fail initially (no translation exists yet), then implementation makes them pass.

**Principle III: Phased Implementation**
✅ **PASS**: Feature builds on P1 (simple query protocol) foundation which is already implemented. Translation applies to both P1 (Simple Query) and P2 (Extended Protocol / prepared statements) per FR-008. No phase sequence violation.

**Principle IV: IRIS Integration**
✅ **PASS**: Implementation uses existing `iris.sql.exec()` embedded Python pattern with `asyncio.to_thread()` for non-blocking execution. Translation occurs in Python code before calling IRIS - no changes to IRIS CallIn configuration needed.

**Principle V: Production Readiness**
✅ **PASS**: Performance requirement PR-001 mandates monitoring of translation overhead. Feature integrates with existing constitutional performance monitoring (5ms SLA tracking). No new security concerns (translation is string manipulation before execution).

**Principle VI: Vector Performance Requirements**
✅ **N/A**: Feature does not involve vector operations. Transaction commands (`BEGIN`, `COMMIT`, `ROLLBACK`) do not interact with HNSW indexes or vector similarity functions.

**Principle VII: Development Environment Synchronization**
✅ **PASS**: Standard development workflow applies - code changes require `docker restart iris-pgwire-db`. E2E tests will validate translation works in real Docker container environment.

**GATE RESULT**: ✅ **ALL PRINCIPLES PASS** - No constitutional violations, no complexity justification needed.

## Project Structure

### Documentation (this feature)
```
specs/022-postgresql-transaction-verb/
├── plan.md              # This file (/plan command output)
├── research.md          # Phase 0 output (minimal - no unknowns)
├── data-model.md        # Phase 1 output (state machine)
├── quickstart.md        # Phase 1 output (developer guide)
├── contracts/           # Phase 1 output (TDD interfaces)
│   └── transaction_translator_interface.py
└── tasks.md             # Phase 2 output (/tasks command - NOT created by /plan)
```

### Source Code (repository root)
```
src/iris_pgwire/
├── iris_executor.py              # PRIMARY INTEGRATION POINT
│                                  # _execute_embedded_async() - add BEGIN→START TRANSACTION translation
│                                  # _execute_external_async() - add BEGIN→START TRANSACTION translation
├── sql_translator/               # SECONDARY INTEGRATION (optional)
│   ├── __init__.py               # Add transaction verb translator
│   ├── transaction_translator.py # NEW: Transaction verb translation logic
│   └── performance_monitor.py    # Track translation overhead metrics
└── vector_optimizer.py           # TERTIARY INTEGRATION
                                   # optimize_vector_query() - add BEGIN→START TRANSACTION translation
                                   # (only if vector queries can appear in transactions)

tests/
├── contract/
│   └── test_transaction_translator_contract.py  # TDD contract tests
├── integration/
│   └── test_transaction_e2e.py                  # Real psql/psycopg tests
└── unit/
    └── test_transaction_translator.py           # Translation logic tests
```

**Structure Decision**: Single project structure with new `sql_translator/transaction_translator.py` module. Integration at 3 points follows Feature 021 pattern (direct execution, external connection, vector optimizer). Transaction translation occurs BEFORE Feature 021 normalization to maintain FR-010 requirement.

## Phase 0: Outline & Research

**Assessment**: No research phase needed - feature scope is well-defined and technically straightforward.

**Rationale**:
1. ✅ **No Technical Unknowns**: Simple string pattern matching and replacement (`BEGIN` → `START TRANSACTION`)
2. ✅ **No Dependency Unknowns**: Uses existing asyncio patterns, integrates with existing SQL execution pipeline
3. ✅ **No Integration Unknowns**: Feature 021 established the SQL normalization pattern - this follows same design
4. ✅ **No Performance Unknowns**: String translation is <0.01ms (well below 0.1ms constitutional target)

**Known Technical Details** (from spec and constitution):
- PostgreSQL `BEGIN` syntax variants: `BEGIN`, `BEGIN TRANSACTION`, `BEGIN WORK`, `BEGIN ISOLATION LEVEL ...`
- IRIS transaction syntax: `START TRANSACTION` (with optional modifiers)
- Transaction control commands that pass through unchanged: `COMMIT`, `ROLLBACK`
- Case-insensitive matching required: `BEGIN`, `begin`, `Begin` all translate
- Integration pattern established by Feature 021: intercept SQL before execution, apply transformation, pass to IRIS

**Output**: Research phase skipped - proceeding directly to design (research.md will document this decision).

## Phase 1: Design & Contracts

**Phase 1 Output Summary**:
- ✅ **data-model.md**: Transaction state machine (IDLE → IN_TRANSACTION → IDLE/ERROR)
- ✅ **contracts/transaction_translator_interface.py**: TDD contract for translation logic
- ✅ **quickstart.md**: Developer usage guide with E2E examples
- ✅ **CLAUDE.md**: Updated via `.specify/scripts/bash/update-agent-context.sh claude`

### 1. Data Model Extraction

**Entities Identified**:
1. **TransactionCommand** (ephemeral)
   - Fields: `command_text` (str), `command_type` (enum: BEGIN/COMMIT/ROLLBACK), `modifiers` (optional str)
   - State: Single-use value object, no persistence
   - Validation: Case-insensitive matching, modifier preservation

2. **TransactionState** (session-scoped)
   - Fields: `status` (enum: IDLE/IN_TRANSACTION/ERROR), `isolation_level` (optional str)
   - State Transitions:
     - IDLE + BEGIN → IN_TRANSACTION
     - IN_TRANSACTION + COMMIT → IDLE
     - IN_TRANSACTION + ROLLBACK → IDLE
     - IN_TRANSACTION + BEGIN → ERROR (nested transactions not supported by IRIS)
   - Lifecycle: Managed by PostgreSQL protocol session handler (outside feature scope)

**Output**: `data-model.md` with entity definitions and state machine diagram

### 2. API Contracts Generation

**Interface Contract** (TDD-first):
```python
# contracts/transaction_translator_interface.py
class TransactionTranslatorInterface:
    """Contract for transaction verb translation"""

    def translate_transaction_command(self, sql: str) -> str:
        """
        Translate PostgreSQL transaction verbs to IRIS equivalents.

        Args:
            sql: SQL command (may contain BEGIN/COMMIT/ROLLBACK)

        Returns:
            Translated SQL with IRIS-compatible transaction verbs

        Raises:
            NotImplementedError: If unsupported transaction syntax detected
        """
        raise NotImplementedError

    def is_transaction_command(self, sql: str) -> bool:
        """Check if SQL is a transaction control command"""
        raise NotImplementedError

    def get_translation_metrics(self) -> Dict[str, Any]:
        """Return performance metrics for constitutional compliance monitoring"""
        raise NotImplementedError
```

**Contract Test Pattern** (must fail initially):
```python
# tests/contract/test_transaction_translator_contract.py
def test_begin_translates_to_start_transaction():
    """FR-001: BEGIN → START TRANSACTION"""
    translator = TransactionTranslator()
    result = translator.translate_transaction_command("BEGIN")
    assert result == "START TRANSACTION"
    # This test MUST fail initially (TransactionTranslator doesn't exist yet)
```

**Output**: `contracts/transaction_translator_interface.py` with full interface definition

### 3. Contract Test Generation

**Test Scenarios** (from functional requirements):
- **FR-001**: `BEGIN` → `START TRANSACTION`
- **FR-002**: `BEGIN TRANSACTION` → `START TRANSACTION`
- **FR-005**: `BEGIN ISOLATION LEVEL READ COMMITTED` → `START TRANSACTION ISOLATION LEVEL READ COMMITTED`
- **FR-006**: `SELECT 'BEGIN'` → unchanged (inside string literal)
- **FR-009**: Case-insensitive: `begin`, `Begin`, `BEGIN` all translate
- **FR-010**: Translation occurs before Feature 021 normalization

**Integration Test Scenarios** (from acceptance scenarios):
1. **E2E psql test**: Real psql client executes `BEGIN; INSERT ...; COMMIT`
2. **E2E psycopg test**: Python driver with parameterized statements in transaction
3. **E2E SQLAlchemy test**: Context manager `with connection.begin():`
4. **Performance test**: Measure translation overhead (must be <0.1ms)

**Output**: Tests written and verified to FAIL (no implementation yet)

### 4. Test Scenarios from User Stories

**Quickstart Test Scenarios** (executable examples):

```python
# Scenario 1: Basic transaction with psql
"""
$ psql -h localhost -p 5432 -U test_user -d USER
psql> BEGIN;
      -- Server translates to: START TRANSACTION
psql> INSERT INTO test_table VALUES (1, 'data');
psql> COMMIT;
      -- Expected: Transaction commits successfully
"""

# Scenario 2: SQLAlchemy context manager
"""
from sqlalchemy import create_engine, text

engine = create_engine("iris+psycopg://localhost:5432/USER")
with engine.connect() as conn:
    with conn.begin():  # Sends BEGIN to server
        conn.execute(text("INSERT INTO test_table VALUES (2, 'data')"))
    # Sends COMMIT on context exit
# Expected: Translation transparent, transaction succeeds
"""

# Scenario 3: Edge case - string literal preservation
"""
SELECT 'Transaction: BEGIN and COMMIT'
-- Expected: String literal unchanged, no translation
"""
```

**Output**: `quickstart.md` with executable test scenarios

### 5. Update Agent File (CLAUDE.md)

**Execution**: Run update script per template requirements:
```bash
.specify/scripts/bash/update-agent-context.sh claude
```

**Updates to CLAUDE.md**:
- Add "Feature 022: PostgreSQL Transaction Verb Compatibility" to recent changes
- Add technical pattern: Translation before normalization pipeline
- Add integration points: iris_executor.py (3 methods), sql_translator/transaction_translator.py
- Add testing approach: E2E with real PostgreSQL clients (psql, psycopg, SQLAlchemy)
- Keep file under 150 lines (remove oldest feature if needed)

**Output**: CLAUDE.md updated incrementally with O(1) operation

## Phase 2: Task Planning Approach

**IMPORTANT**: This section describes what the /tasks command will do - DO NOT execute during /plan.

### Task Generation Strategy

**Input Sources**:
1. **Functional Requirements** (FR-001 through FR-010): Each requirement → 1-2 implementation tasks
2. **Performance Requirements** (PR-001 through PR-003): Validation tasks with metrics collection
3. **Testing Requirements** (TR-001 through TR-005): E2E test tasks with real clients
4. **Contract Tests** (from Phase 1): TDD tasks (tests first, implementation second)

**Task Categories**:
1. **Contract Tests** (T001-T005): Write failing tests for each functional requirement [P]
2. **Core Implementation** (T006-T010): Implement TransactionTranslator to make tests pass
3. **Integration** (T011-T015): Integrate with iris_executor.py (3 execution paths)
4. **E2E Validation** (T016-T020): Real client testing (psql, psycopg, SQLAlchemy)
5. **Performance** (T021-T023): Measure overhead, validate <0.1ms SLA
6. **Edge Cases** (T024-T028): String literals, nested transactions, case-insensitivity
7. **Polish** (T029-T030): Logging, error messages, documentation

**Task Ordering Strategy**:
- **TDD Order**: Tests before implementation (T001-T005 before T006-T010)
- **Dependency Order**: Core implementation before integration (T010 before T011)
- **Parallelization**: Mark independent tasks with [P] for parallel execution
  - Contract tests can run in parallel (T001-T005 all [P])
  - Integration tasks must be sequential (depend on T010 completion)

**Estimated Output**: 25-30 numbered, ordered tasks in tasks.md

**Example Task Structure**:
```markdown
## T001: Contract Test - BEGIN Translation [P]
**Type**: Contract Test (TDD - must fail initially)
**Dependencies**: None
**Effort**: 15 minutes

Write contract test for FR-001: `BEGIN` → `START TRANSACTION`
Test file: `tests/contract/test_transaction_translator_contract.py`
Expected: Test FAILS (TransactionTranslator class doesn't exist)

**Acceptance**:
- [ ] Test written and executes
- [ ] Test fails with clear error (class not found)
- [ ] Test documents expected behavior per FR-001
```

**IMPORTANT**: This phase is executed by the /tasks command, NOT by /plan

## Phase 3+: Future Implementation

*These phases are beyond the scope of the /plan command*

**Phase 3**: Task execution (/tasks command creates tasks.md)
**Phase 4**: Implementation (execute tasks.md following constitutional principles)
**Phase 5**: Validation (run tests, execute quickstart.md, performance validation)

## Complexity Tracking

*No entries required - Constitutional Check passed with no violations*

## Progress Tracking

*This checklist is updated during execution flow*

**Phase Status**:
- [x] Phase 0: Research complete (/plan command) - Skipped (no unknowns)
- [x] Phase 1: Design complete (/plan command) - All artifacts generated
- [x] Phase 2: Task planning complete (/plan command - describe approach only)
- [ ] Phase 3: Tasks generated (/tasks command) - **NEXT STEP**
- [ ] Phase 4: Implementation complete
- [ ] Phase 5: Validation passed

**Gate Status**:
- [x] Initial Constitution Check: PASS (all 7 principles compliant)
- [x] Post-Design Constitution Check: PASS (no new violations)
- [x] All NEEDS CLARIFICATION resolved (none existed)
- [x] Complexity deviations documented (N/A - no deviations)

---
*Based on Constitution v1.3.0 - See `.specify/memory/constitution.md`*

# Feature Specification: Test Coverage 90%

**Feature Branch**: `042-test-coverage-90`
**Created**: 2026-06-24
**Status**: Draft
**Input**: User description: "Increase iris-pgwire test coverage from 47% to 90%"

## User Scenarios & Testing *(mandatory)*

### User Story 1 — Fix Stale Contract Tests (Priority: P1)

15 contract tests fail with `AttributeError` because they reference API methods that
were renamed or removed: `SQLTranslator.translate`, `VectorQueryOptimizer.validate_sql`,
and `PGWireExecutor.execute_with_timeout`. These tests were written TDD-first but never
updated when the implementation diverged.

**Why this priority**: These tests document existing intent — fixing them is pure
recovery with maximum coverage gain per effort, no new code required.

**Independent Test**: Run `pytest tests/contract/test_translation_contracts.py
tests/contract/test_vector_optimizer_validation.py tests/contract/test_benchmark_timeouts.py -v`
— all 16 tests pass.

**Acceptance Scenarios**:

1. **Given** `test_translation_contracts.py` references `SQLTranslator.translate`, **When**
   the test is updated to the current API, **Then** all 6 tests in that file pass.
2. **Given** `test_vector_optimizer_validation.py` calls `optimizer.validate_sql()`, **When**
   the method is added or tests are updated to `optimize_query()`, **Then** all 5 tests pass.
3. **Given** `test_benchmark_timeouts.py` references `PGWireExecutor.execute_with_timeout`,
   **When** tests are updated to the current timeout API, **Then** all 5 tests pass.

---

### User Story 2 — Fix Code Bugs Surfaced by Tests (Priority: P1)

Several failing tests expose real bugs: `AttributeError: 'list' object has no attribute
'upper'` in the license checker (3 tests), a timestamp normalisation regression for
timezone-offset timestamps (1 test), boolean default translation failures (2 tests),
and 5 tests requiring `sqlalchemy_iris.psycopg` to be an optional import.

**Why this priority**: These are real production bugs, not test harness issues.

**Independent Test**: `pytest tests/contract/test_security_contract.py
tests/unit/test_timestamp_normalization_logic.py tests/contract/test_boolean_defaults.py -v`
all pass.

**Acceptance Scenarios**:

1. **Given** the license validator receives a list of license strings, **When**
   `check_license_compatibility` is called, **Then** it returns a valid result without
   raising `AttributeError`.
2. **Given** a timestamp `2026-01-29T21:27:38.111+00:00`, **When** normalised, **Then**
   the output matches the expected IRIS-compatible format.
3. **Given** `sqlalchemy_iris.psycopg` is absent, **When** the async dialect contract
   tests run, **Then** they skip gracefully instead of erroring.

---

### User Story 3 — Add Tests for Zero-Coverage Modules (Priority: P2)

Ten source modules have 0% coverage. The largest are `ddl_parser.py` (449 stmts),
`ddl_translator.py` (178 stmts), `migrations/executor.py` (145 stmts),
`type_translator.py` (95 stmts), and `_type_mapping.py` (88 stmts). Together they
represent ~1,027 statements — roughly 6 percentage points of coverage.

**Why this priority**: These modules contain production DDL translation and migration
logic with no test safety net. New tests provide the biggest single coverage jump
available without requiring a live IRIS container.

**Independent Test**: `pytest tests/unit/test_ddl_parser.py tests/unit/test_ddl_translator.py
tests/unit/test_migrations_executor.py tests/unit/test_type_translator.py
tests/unit/test_type_mapping.py -v` — all pass with no IRIS container.

**Acceptance Scenarios**:

1. **Given** a `CREATE TABLE` PostgreSQL DDL, **When** `DDLParser.parse()` processes it,
   **Then** it returns a `DDLStatement` with correct columns and constraints.
2. **Given** a parsed `DDLStatement`, **When** `DDLTranslator` translates it, **Then**
   `translated_sql` is valid IRIS-compatible SQL.
3. **Given** a `MigrationExecutor` with a mock DBAPI connection, **When**
   `create_journal_table()` is called, **Then** journal DDL executes once and
   `is_migration_applied()` returns `False` for unknown hashes.
4. **Given** PostgreSQL type strings (`text`, `uuid`, `jsonb`, `vector(1536)`), **When**
   `TypeTranslator` maps them, **Then** correct IRIS equivalents are returned.
5. **Given** IRIS JDBC type codes, **When** `_type_mapping` helpers convert them, **Then**
   correct PostgreSQL OIDs and Python values are returned.

---

### User Story 4 — Mock OAuth/Wallet Contract Tests (Priority: P2)

20 OAuth and Wallet contract tests fail because they require live IRIS endpoints.
The `OAuthBridge` and `WalletCredentials` classes make live calls during construction
or first use, with no injection point for mocks.

**Why this priority**: 20 tests is the largest single failing block. Fixing them
completes the auth contract suite without requiring a container.

**Independent Test**: `pytest tests/contract/test_oauth_bridge_contract.py
tests/contract/test_wallet_credentials_contract.py -v` — all pass with mocked IRIS.

**Acceptance Scenarios**:

1. **Given** `OAuthBridge` accepts a mock IRIS connection, **When** contract tests run,
   **Then** token exchange, validation, and refresh paths are exercised without live IRIS.
2. **Given** `WalletCredentials` accepts a mock wallet API, **When** contract tests run,
   **Then** retrieval, storage failure, and audit trail paths are covered.

---

### Edge Cases

- `DDLParser` receiving a SQL string with only comments and no DDL — must return empty list.
- `TypeTranslator` receiving an unknown PostgreSQL type — must raise `DDLTranslationError`.
- `MigrationExecutor` when the journal table already exists — must not error on double-create.
- Timestamp normaliser receiving a timestamp with fractional seconds and non-UTC offset.
- License checker receiving an empty list — must not crash.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: All contract/unit tests referencing removed or renamed API methods must be
  updated to match the current public API; where the old method expressed intent not
  covered by the current API, the method must be added.
- **FR-002**: `check_license_compatibility` must accept both `str` and `List[str]` input
  without raising `AttributeError`.
- **FR-003**: The timestamp normaliser must correctly handle ISO 8601 timestamps with
  numeric timezone offsets (e.g., `+00:00`, `-05:30`) and produce IRIS-accepted output.
- **FR-004**: `sqlalchemy_iris.psycopg` must be imported inside a `try/except ImportError`
  block so dependent tests skip cleanly when the package is absent.
- **FR-005**: New unit tests for `ddl_parser.py` must achieve ≥80% line coverage.
- **FR-006**: New unit tests for `ddl_translator.py` must achieve ≥80% line coverage.
- **FR-007**: New unit tests for `migrations/executor.py` must achieve ≥80% line coverage
  using a mock DBAPI connection — no live IRIS required.
- **FR-008**: New unit tests must achieve ≥80% line coverage across `type_translator.py`,
  `_type_mapping.py`, `constraint_translator.py`, `index_validator.py`,
  `reserved_words.py`, and `config.py`.
- **FR-009**: OAuth and Wallet contract tests must use mocks so no test in
  `tests/contract/` requires a live IRIS container.
- **FR-010**: `pytest tests/unit/ tests/contract/ --cov=src/iris_pgwire --cov-fail-under=90`
  must exit 0.

### Key Entities

- **DDLParser**: Parses PostgreSQL DDL into structured `DDLStatement` objects.
- **DDLTranslator**: Converts `DDLStatement` objects to IRIS-compatible SQL strings.
- **MigrationExecutor**: Applies Drizzle migration files to IRIS via a DBAPI connection,
  tracking applied migrations in a journal table.
- **TypeTranslator**: Maps PostgreSQL type names to IRIS equivalents with precision handling.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: `pytest tests/unit/ tests/contract/ --cov=src/iris_pgwire --cov-fail-under=90`
  exits 0 with no IRIS container running.
- **SC-002**: Failing test count drops from 85 to ≤5 (residual failures may only be
  tests that genuinely require a live container, which become skips).
- **SC-003**: No previously-passing test is broken by these changes.
- **SC-004**: All new test files use existing project conventions (markers, conftest
  fixtures, no hardcoded ports).

## Assumptions

- Tests that genuinely require a live IRIS container may remain as skips — they do not
  count against the 90% target measured over `tests/unit/` and `tests/contract/`.
- `sqlalchemy_iris` and `pyroma` are optional dependencies; tests needing them skip
  gracefully if absent.
- The 90% target is measured on statement coverage, not branch coverage.
- `protocol.py` (4700 lines) and `iris_executor.py` already have partial coverage;
  90% overall does not require exhaustive branch coverage of those files.

## Out of Scope

- Integration tests requiring a live IRIS container (`tests/integration/`, `tests/e2e/`)
- Performance benchmark tests
- New feature development beyond what is needed to make existing tests pass

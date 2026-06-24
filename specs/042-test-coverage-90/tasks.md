# Tasks: Test Coverage 90%

**Input**: Design documents from `/specs/042-test-coverage-90/`
**Prerequisites**: plan.md ✅, spec.md ✅

**Organization**: Tasks grouped by user story to enable independent implementation and testing.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies)
- **[Story]**: Which user story this task belongs to (US1–US4)

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Verify test environment; confirm baseline before any changes.

- [ ] T001 Confirm working directory is `/Users/tdyar/ws/iris-pgwire-gh` and branch `042-test-coverage-90` is checked out
- [ ] T002 Run `pytest tests/unit/ tests/contract/ --tb=no -q 2>/dev/null | tail -5` to capture baseline pass/fail counts

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Bug fixes that unblock the largest blocks of failing tests. Must complete before story phases.

**⚠️ CRITICAL**: All Phase 3 and Phase 4 contract tests depend on these fixes.

- [ ] T003 Fix `check_license_compatibility` in `src/iris_pgwire/quality/security_validator.py` — change param from `str` to `str | list[str]`; when list, iterate and call existing logic per item, accumulate results (fixes 3 failing tests)
- [ ] T004 Fix `_convert_iso_timestamp` in `src/iris_pgwire/dbapi_executor.py` — after UTC conversion, truncate microseconds to milliseconds: `result = parts[0] + "." + parts[1][:3]` where parts = result.rsplit(".", 1) (fixes timestamp regression test)
- [ ] T005 Guard `sqlalchemy_iris.psycopg` import in `tests/contract/test_async_dialect_contract.py` — wrap in `try/except ImportError` then `pytest.skip("sqlalchemy_iris.psycopg not installed")` at module or test level (fixes 5 skips)

**Checkpoint**: `pytest tests/contract/test_security_contract.py tests/unit/test_timestamp_normalization_logic.py -v` — all pass.

---

## Phase 3: User Story 1 — Fix Stale Contract Tests (P1)

**Goal**: All 16 contract tests in 3 stale-API files pass by aligning APIs.

**Independent Test**: `pytest tests/contract/test_translation_contracts.py tests/contract/test_vector_optimizer_validation.py tests/contract/test_benchmark_timeouts.py -v` — all 16 pass.

### Implementation for User Story 1

- [ ] T006 [P] [US1] Add `translate(request)` method to `SQLTranslator` in `src/iris_pgwire/sql_translator/__init__.py` — wrapper that accepts a `TranslationRequest`-like object and delegates to `IRISSQLNormalizer.normalize_sql()`; OR update `tests/contract/test_translation_contracts.py` to call the current `normalize_sql()` API directly (whichever approach matches the test intent)
- [ ] T007 [P] [US1] Add `validate_sql(sql: str) -> ValidationResult` method to `VectorQueryOptimizer` in `src/iris_pgwire/vector_optimizer.py` — `ValidationResult` is a simple dataclass with fields: `is_valid: bool`, `has_brackets_in_vector_literals: bool`, `error_message: str | None`; add dataclass at top of file
- [ ] T008 [P] [US1] Add `execute_with_timeout(sql: str, timeout_seconds: float)` method to `PGWireExecutor` in `benchmarks/executors/pgwire_executor.py` — wraps `execute()` with `asyncio.wait_for` or similar timeout mechanism
- [ ] T009 [US1] Run `pytest tests/contract/test_translation_contracts.py tests/contract/test_vector_optimizer_validation.py tests/contract/test_benchmark_timeouts.py -v` and confirm all 16 pass

**Checkpoint**: User Story 1 complete — 16 previously-failing contract tests now pass.

---

## Phase 4: User Story 2 — Fix Code Bugs Surfaced by Tests (P1)

**Goal**: Remaining bug-surface tests pass; `sqlalchemy_iris` tests skip cleanly.

**Independent Test**: `pytest tests/contract/test_security_contract.py tests/unit/test_timestamp_normalization_logic.py tests/contract/test_boolean_defaults.py tests/contract/test_async_dialect_contract.py -v` — all pass or skip.

### Implementation for User Story 2

- [ ] T010 [US2] Verify `tests/contract/test_boolean_defaults.py` uses correct `BooleanTranslator` API — confirm `BooleanTranslator().translate(sql)` returns `(result_str, count)` tuple; if test uses different signature, update test to match `src/iris_pgwire/sql_translator/boolean_translator.py` actual API
- [ ] T011 [US2] Run full `pytest tests/contract/ -v --tb=short 2>/dev/null | grep -E "PASSED|FAILED|ERROR|SKIP"` to capture remaining failures after T003–T010

**Checkpoint**: User Story 2 complete — no new failures in contract suite; `sqlalchemy_iris` tests skip gracefully.

---

## Phase 5: User Story 3 — Add Tests for Zero-Coverage Modules (P2)

**Goal**: 9 zero-coverage modules gain ≥80% line coverage via new unit tests.

**Independent Test**: `pytest tests/unit/test_ddl_parser.py tests/unit/test_ddl_translator.py tests/unit/test_migrations_executor.py tests/unit/test_type_translator.py tests/unit/test_type_mapping.py tests/unit/test_constraint_translator.py tests/unit/test_index_validator.py tests/unit/test_reserved_words.py tests/unit/test_config.py -v` — all pass, no IRIS container.

### Tests for User Story 3 (written test-first — they ARE the implementation)

- [ ] T012 [P] [US3] Write `tests/unit/test_ddl_parser.py` — test `DDLParser.parse()` with: `CREATE TABLE` with columns+constraints, empty/comment-only input, multiple statements, `CREATE INDEX`, primary key, unique constraint; assert `DDLStatement` fields; target ≥80% of `src/iris_pgwire/sql_translator/ddl_parser.py` (449 stmts)
- [ ] T013 [P] [US3] Write `tests/unit/test_type_translator.py` — test `TypeTranslator` mapping for: `text`, `varchar(255)`, `integer`, `bigint`, `boolean`, `jsonb`, `uuid`, `timestamp`, `vector(1536)`, unknown type raises `DDLTranslationError`; target ≥80% of `src/iris_pgwire/sql_translator/type_translator.py` (95 stmts)
- [ ] T014 [P] [US3] Write `tests/unit/test_type_mapping.py` — test IRIS JDBC type code → PostgreSQL OID conversion helpers and POSIXTIME handling; cover public functions in `src/iris_pgwire/_type_mapping.py` (88 stmts) at ≥80%
- [ ] T015 [P] [US3] Write `tests/unit/test_constraint_translator.py` — test `ConstraintTranslator` for PRIMARY KEY, UNIQUE, FOREIGN KEY, NOT NULL, CHECK constraints; all 20 stmts in `src/iris_pgwire/sql_translator/constraint_translator.py`
- [ ] T016 [P] [US3] Write `tests/unit/test_index_validator.py` — test `IndexValidator` with valid/invalid index definitions; all 21 stmts in `src/iris_pgwire/sql_translator/index_validator.py`
- [ ] T017 [P] [US3] Write `tests/unit/test_reserved_words.py` — test `ReservedWordChecker` with IRIS-reserved words and safe identifiers; all 16 stmts in `src/iris_pgwire/sql_translator/reserved_words.py`
- [ ] T018 [P] [US3] Write `tests/unit/test_config.py` — test `DDLTranslationConfig` defaults and custom values; all 9 stmts in `src/iris_pgwire/config.py`
- [ ] T019 [US3] Write `tests/unit/test_ddl_translator.py` — test `DDLTranslator` end-to-end: `CREATE TABLE` → IRIS SQL, `CREATE INDEX` → IRIS syntax, `ALTER TABLE ADD COLUMN` → IRIS, type substitutions applied; target ≥80% of `src/iris_pgwire/sql_translator/ddl_translator.py` (178 stmts); depends on T012 (DDLParser needed as input source)
- [ ] T020 [US3] Write `tests/unit/test_migrations_executor.py` — test `MigrationExecutor` with mock `connection` (use `unittest.mock.MagicMock`): `create_journal_table()` executes DDL once, `is_migration_applied(hash)` returns False for unknown hash, `record_migration()` inserts row, double-create journal does not error; target ≥80% of `src/iris_pgwire/migrations/executor.py` (145 stmts)
- [ ] T021 [US3] Run `pytest tests/unit/ -v --cov=src/iris_pgwire/sql_translator --cov=src/iris_pgwire/migrations --cov=src/iris_pgwire/_type_mapping --cov=src/iris_pgwire/config --cov-report=term-missing 2>/dev/null | tail -40` — verify ≥80% on all targeted modules

**Checkpoint**: User Story 3 complete — 9 previously-untested modules now have ≥80% coverage.

---

## Phase 6: User Story 4 — Mock OAuth/Wallet Contract Tests (P2)

**Goal**: 20 OAuth/Wallet contract tests pass using mocks; no live IRIS container needed.

**Independent Test**: `pytest tests/contract/test_oauth_bridge_contract.py tests/contract/test_wallet_credentials_contract.py -v` — all pass.

### Implementation for User Story 4

- [ ] T022 [P] [US4] Fix `tests/contract/test_oauth_bridge_contract.py` — add `@patch("iris_pgwire.auth.oauth_bridge.iris")` fixture at class or function level; mock `iris.cls()` to return a `MagicMock`; ensure token exchange, validation, and refresh code paths are exercised; no live IRIS calls
- [ ] T023 [P] [US4] Fix `tests/contract/test_wallet_credentials_contract.py` — add `@patch("iris_pgwire.auth.wallet_credentials.iris")` fixture; mock `iris.cls()` return value such that `mock_obj.GetSecret.return_value = "secret_abc123xyz789abc"` (≥32 chars); exercise retrieval, storage failure, and audit trail paths
- [ ] T024 [US4] Run `pytest tests/contract/test_oauth_bridge_contract.py tests/contract/test_wallet_credentials_contract.py -v` — confirm all 20 pass without container

**Checkpoint**: User Story 4 complete — 20 auth contract tests now pass with mocks.

---

## Phase 7: Coverage Gate

**Purpose**: Verify 90% overall coverage target is met.

- [ ] T025 Run `pytest tests/unit/ tests/contract/ --cov=src/iris_pgwire --cov-fail-under=90 --cov-report=term-missing -q 2>&1 | tail -30` — must exit 0
- [ ] T026 If coverage is below 90%, identify the highest-gap modules from the report and write additional targeted tests until the gate passes
- [ ] T027 Run `pytest tests/unit/ tests/contract/ -q --tb=no 2>&1 | tail -5` — confirm failing count ≤5 (residual = genuine container-require tests that skip)

---

## Phase 8: Polish

- [ ] T028 [P] Run `markdownlint-cli2 --fix "specs/042-test-coverage-90/*.md"` and `prettier --write "specs/042-test-coverage-90/*.md"`
- [ ] T029 Commit all changes: test files, source fixes, spec docs

---

## Dependencies & Execution Order

### Phase Dependencies

- **Phase 1 (Setup)**: No dependencies — start immediately
- **Phase 2 (Foundational)**: Depends on Phase 1 — blocks Phases 3–4
- **Phase 3 (US1)**: Depends on Phase 2
- **Phase 4 (US2)**: Depends on Phase 2 (T003, T004, T005 must be done)
- **Phase 5 (US3)**: Independent — can run in parallel with Phases 3–4 after Phase 2
- **Phase 6 (US4)**: Independent — can run in parallel with Phases 3–5 after Phase 2
- **Phase 7 (Gate)**: Depends on all prior phases

### User Story Dependencies

- **US1**: Depends on Phase 2 (no inter-story dependency)
- **US2**: Depends on T003, T004, T005 from Phase 2
- **US3**: Depends on Phase 1 only — new test files, no source changes
- **US4**: Depends on Phase 2 bug fixes for clean baseline

### Parallel Opportunities (within Phase 5 — US3 is largest)

T012, T013, T014, T015, T016, T017, T018 are all [P] — independent files, launch together:

```bash
# Fan out US3 test writing (all independent):
Task: "Write tests/unit/test_ddl_parser.py"          # T012
Task: "Write tests/unit/test_type_translator.py"      # T013
Task: "Write tests/unit/test_type_mapping.py"         # T014
Task: "Write tests/unit/test_constraint_translator.py" # T015
Task: "Write tests/unit/test_index_validator.py"      # T016
Task: "Write tests/unit/test_reserved_words.py"       # T017
Task: "Write tests/unit/test_config.py"               # T018
# Then sequentially (depend on DDLParser output):
Task: "Write tests/unit/test_ddl_translator.py"       # T019
Task: "Write tests/unit/test_migrations_executor.py"  # T020
```

Also parallel across user stories after Phase 2:

```bash
Task: "US1 — fix 3 stale-API contract test files"    # T006–T008
Task: "US3 — write 7 independent unit test files"    # T012–T018
Task: "US4 — mock OAuth/Wallet contract tests"       # T022–T023
```

---

## Implementation Strategy

### MVP (US1 + US2 only — fixes all P1 failures)

1. Phase 1 Setup
2. Phase 2 Foundational (T003–T005)
3. Phase 3 US1 (T006–T009) — 16 tests fixed
4. Phase 4 US2 (T010–T011) — remaining bug-surface tests pass
5. **STOP**: 85 → ≤15 failures; coverage improvement from restored tests

### Full Delivery (all 4 stories)

1. Phases 1–2 (sequential)
2. Phases 3, 5, 6 in parallel (US1 + US3 + US4)
3. Phase 4 (US2, after Phase 2)
4. Phase 7 coverage gate
5. Phase 8 polish

---

## Notes

- [P] tasks operate on different files — safe to fan out to parallel agents
- [US3] tests are the primary coverage driver — 9 files × avg 50 stmts = ~450 new covered statements
- Residual failures (≤5) are expected for tests that genuinely require live IRIS; these become `pytest.skip`
- Total tasks: 29 | P1 tasks: T003–T011 (9) | P2 tasks: T012–T024 (13)

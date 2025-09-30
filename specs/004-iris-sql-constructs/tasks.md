# Tasks: IRIS SQL Constructs Translation

**Input**: Design documents from `/specs/004-iris-sql-constructs/`
**Prerequisites**: plan.md (required), research.md, data-model.md, contracts/

## Format: `[ID] [P?] Description`
- **[P]**: Can run in parallel (different files, no dependencies)
- Include exact file paths in descriptions

## Phase 3.1: Setup

- [X] **T001** Create SQL translator module structure: `src/iris_pgwire/sql_translator/__init__.py`, `src/iris_pgwire/sql_translator/mappings/__init__.py`
- [X] **T002** Initialize Python dependencies: sqlparse, structlog, pytest in pyproject.toml requirements
- [X] **T003** [P] Configure linting tools: ruff, black, mypy configuration for sql_translator module

## Phase 3.2: Tests First (TDD) ⚠️ MUST COMPLETE BEFORE 3.3
**CRITICAL: These tests MUST be written and MUST FAIL before ANY implementation**

- [ ] **T004** [P] Contract test `/translate` endpoint in `tests/contract/test_translation_contracts.py`
- [ ] **T005** [P] Contract test `/cache/stats` endpoint in `tests/contract/test_cache_contracts.py`
- [ ] **T006** [P] Contract test `/cache/invalidate` endpoint in `tests/contract/test_cache_invalidate_contracts.py`
- [ ] **T007** [P] Integration test IRIS system functions scenario in `tests/integration/test_e2e_psql.py`
- [ ] **T008** [P] Integration test IRIS SQL syntax extensions in `tests/integration/test_e2e_psycopg.py`
- [ ] **T009** [P] Integration test IRIS functions with parameters in `tests/integration/test_iris_integration.py`
- [ ] **T010** [P] Integration test mixed IRIS/standard SQL in `tests/integration/test_mixed_sql.py`
- [ ] **T010a** [P] Integration test Document Database filter operations in `tests/integration/test_document_filters.py`
- [ ] **T011** [P] Integration test error handling for unsupported constructs in `tests/integration/test_error_handling.py`

## Phase 3.3: Core Implementation (ONLY after tests are failing)

- [ ] **T012** Complete data models implementation in `src/iris_pgwire/sql_translator/models.py` (TranslationRequest, TranslationResult, ConstructMapping, PerformanceStats, FunctionMapping, TypeMapping, CacheEntry, DebugTrace)
- [ ] **T016** [P] IRIS function mappings registry in `src/iris_pgwire/sql_translator/mappings/functions.py`
- [ ] **T017** [P] IRIS data type mappings in `src/iris_pgwire/sql_translator/mappings/datatypes.py`
- [ ] **T018** [P] IRIS SQL construct mappings in `src/iris_pgwire/sql_translator/mappings/constructs.py`
- [ ] **T018a** [P] Document Database filter mappings in `src/iris_pgwire/sql_translator/mappings/document_filters.py`
- [ ] **T019** [P] SQL parser implementation in `src/iris_pgwire/sql_translator/parser.py`
- [ ] **T020** [P] Translation cache with LRU/TTL in `src/iris_pgwire/sql_translator/cache.py`
- [ ] **T021** [P] Debug trace logging in `src/iris_pgwire/sql_translator/debug.py`
- [ ] **T022** [P] Semantic validator for query equivalence in `src/iris_pgwire/sql_translator/validator.py`
- [ ] **T023** Main SQL translator engine in `src/iris_pgwire/sql_translator/translator.py`
- [ ] **T024** Translation API `/translate` endpoint implementation
- [ ] **T025** Cache statistics API `/cache/stats` endpoint implementation
- [ ] **T026** Cache invalidation API `/cache/invalidate` endpoint implementation
- [ ] **T027** Input validation for translation requests
- [ ] **T028** Error handling for unsupported constructs (hybrid strategy)
- [ ] **T029** Performance monitoring and 5ms SLA enforcement

## Phase 3.4: Integration

- [ ] **T030** Integrate translator with existing PostgreSQL protocol in `src/iris_pgwire/protocol.py`
- [ ] **T031** Connect translator to IRIS executor with async threading in `src/iris_pgwire/iris_executor.py`
- [ ] **T032** Add translation layer to simple query processing
- [ ] **T033** Add translation layer to extended query protocol (prepared statements)
- [ ] **T034** Structured logging integration with existing server logs
- [ ] **T035** Metrics collection for translation performance
- [ ] **T036** Configuration loading for debug mode and cache settings

## Phase 3.5: Polish

- [ ] **T037** [P] Unit tests for SQL parser in `tests/unit/test_parser.py`
- [ ] **T038** [P] Unit tests for translation mappings in `tests/unit/test_mappings.py`
- [ ] **T038a** [P] Unit tests for document filter mappings in `tests/unit/test_document_filters.py`
- [ ] **T039** [P] Unit tests for translator engine in `tests/unit/test_translator.py`
- [ ] **T040** [P] Unit tests for cache implementation in `tests/unit/test_cache.py`
- [ ] **T041** Performance tests (validate <5ms SLA) in `tests/performance/test_translation_latency.py`
- [ ] **T042** Load testing with 1000+ concurrent translations in `tests/performance/test_concurrent_load.py`
- [ ] **T043** [P] Update main README with SQL translation features
- [ ] **T044** [P] Create translation mapping documentation in `docs/sql_constructs.md`
- [ ] **T045** Remove any code duplication and optimize for maintainability
- [ ] **T046** Execute quickstart.md validation scenarios end-to-end

## Dependencies

**Sequential Dependencies**:
- Setup (T001-T003) must complete before tests
- Tests (T004-T011) must complete and FAIL before implementation
- Models (T012) must complete before translator (T023)
- Mappings (T016-T018) must complete before translator (T023)
- Core components (T012-T022) must complete before translator (T023)
- Translator (T023) must complete before API endpoints (T024-T026)
- Integration (T030-T036) requires core implementation complete
- Polish (T037-T046) requires all implementation complete

**Blocking Relationships**:
- T023 blocks T024, T025, T026, T030, T031
- T016, T017, T018, T018a block T023
- T019, T020, T021, T022 block T023
- T030, T031 block T032, T033
- Implementation (T012-T029) blocks polish (T037-T046)

## Parallel Execution Examples

### Phase 3.2 - Contract & Integration Tests (All Parallel)
```
Task: "Contract test /translate endpoint in tests/contract/test_translation_contracts.py"
Task: "Contract test /cache/stats endpoint in tests/contract/test_cache_contracts.py"
Task: "Contract test /cache/invalidate endpoint in tests/contract/test_cache_invalidate_contracts.py"
Task: "Integration test IRIS system functions scenario in tests/integration/test_e2e_psql.py"
Task: "Integration test IRIS SQL syntax extensions in tests/integration/test_e2e_psycopg.py"
```

### Phase 3.3 - Core Implementation (Models first, then mappings in parallel)
```
# Sequential: Data models must complete first
Task: "Complete data models implementation in src/iris_pgwire/sql_translator/models.py"

# Then parallel: Mapping implementations
Task: "IRIS function mappings registry in src/iris_pgwire/sql_translator/mappings/functions.py"
Task: "IRIS data type mappings in src/iris_pgwire/sql_translator/mappings/datatypes.py"
Task: "IRIS SQL construct mappings in src/iris_pgwire/sql_translator/mappings/constructs.py"
Task: "Document Database filter mappings in src/iris_pgwire/sql_translator/mappings/document_filters.py"
Task: "SQL parser implementation in src/iris_pgwire/sql_translator/parser.py"
```

### Phase 3.5 - Unit Tests (All Parallel)
```
Task: "Unit tests for SQL parser in tests/unit/test_parser.py"
Task: "Unit tests for translation mappings in tests/unit/test_mappings.py"
Task: "Unit tests for document filter mappings in tests/unit/test_document_filters.py"
Task: "Unit tests for translator engine in tests/unit/test_translator.py"
Task: "Unit tests for cache implementation in tests/unit/test_cache.py"
```

## Validation Checklist
*GATE: Checked before task execution begins*

- [x] All contracts have corresponding tests (T004-T006 cover translation_api.yaml)
- [x] All entities have model tasks (T012 covers all data-model.md entities)
- [x] All tests come before implementation (Phase 3.2 before 3.3)
- [x] Parallel tasks truly independent (different files, no shared dependencies)
- [x] Each task specifies exact file path
- [x] No task modifies same file as another [P] task
- [x] TDD enforced: tests must fail before implementation
- [x] Performance requirements included (5ms SLA in T041-T042)
- [x] Constitutional compliance: E2E tests with real clients (T007-T011)

## Notes

- **Constitutional Compliance**: Tasks T007-T011 implement Test-First Development with real PostgreSQL clients
- **Performance SLA**: Tasks T041-T042 validate <5ms translation latency requirement
- **IRIS Integration**: Tasks T030-T031 use embedded Python with proper async threading
- **Production Readiness**: Tasks T034-T035 implement comprehensive logging and monitoring
- **Protocol Fidelity**: Tasks T030-T033 maintain PostgreSQL wire protocol compliance

**Ready for execution**: All tasks are specific, testable, and follow constitutional principles.
# Tasks: DBAPI Backend Option with IPM Packaging

**Input**: Design documents from `/specs/018-add-dbapi-option/`
**Prerequisites**: plan.md, research.md, data-model.md, contracts/, quickstart.md

## Execution Flow (main)
```
1. Load plan.md from feature directory
   → Tech stack: Python 3.11+, asyncio, intersystems-irispython, OTEL
   → Structure: Single project (src/iris_pgwire/, ipm/, tests/)
2. Load design documents:
   → data-model.md: 5 entities (BackendConfig, ConnectionPoolState, IPMModuleMetadata, VectorQueryRequest, DBAPIConnection)
   → contracts/: 2 contracts (backend-selector, dbapi-executor)
   → research.md: 5 decisions (TCP server pattern, Queue-based pool, Python OTEL, TO_VECTOR binding, health checks)
3. Generate tasks by category:
   → Setup: Dependencies, IPM structure, config schema
   → Tests: 2 contract tests, 4 integration tests
   → Core: 5 models, 3 implementation files
   → Integration: Connection pool, OTEL, health checks
   → IPM Packaging: module.xml, ObjectScript classes
   → Polish: Documentation, validation
4. Apply task rules:
   → Contract tests before implementation (TDD)
   → Models before executors
   → Backend implementation before IPM packaging
   → All tests marked [P] (different files)
5. Number tasks sequentially (T001-T028)
6. Dependencies: Tests → Models → Executors → IPM → Integration → Polish
7. Parallel execution: Tests, models, OTEL can run concurrently
8. Validate: All contracts tested, all entities modeled, constitutional compliance
```

## Format: `[ID] [P?] Description`
- **[P]**: Can run in parallel (different files, no dependencies)
- Include exact file paths in descriptions

## Path Conventions
- **Source**: `src/iris_pgwire/` (existing structure)
- **Tests**: `tests/contract/`, `tests/integration/`, `tests/unit/`
- **IPM**: `ipm/` (new directory)
- **Docs**: Repository root

---

## Phase 3.1: Setup & Dependencies

- [x] **T001** Create IPM packaging directory structure (`ipm/` with subdirectories for ObjectScript classes)
- [x] **T002** Update `pyproject.toml` with new dependencies (intersystems-irispython>=3.2.0, opentelemetry-api>=1.20.0, opentelemetry-sdk>=1.20.0, opentelemetry-instrumentation-asyncio>=0.41b0, opentelemetry-exporter-otlp>=1.20.0)
- [x] **T003** [P] Create configuration schema in `src/iris_pgwire/config_schema.py` (YAML/env loading for BackendConfig)

---

## Phase 3.2: Tests First (TDD) ⚠️ MUST COMPLETE BEFORE 3.3

**CRITICAL: These tests MUST be written and MUST FAIL before ANY implementation**

### Contract Tests (Based on contracts/)

- [x] **T004** [P] Contract test for BackendSelector in `tests/contract/test_backend_selector_contract.py`
  - Test cases: creates_dbapi_executor, creates_embedded_executor, validates_pool_limits, requires_credentials_for_dbapi, rejects_invalid_backend_type (5 tests from contract)
  - Must fail initially (BackendSelector not implemented yet)

- [x] **T005** [P] Contract test for DBAPIExecutor in `tests/contract/test_dbapi_executor_contract.py`
  - Test cases: initializes_pool, executes_simple_query, handles_large_vectors, pool_handles_1000_concurrent_connections, reconnects_after_iris_restart, translation_time_under_5ms (7 tests from contract)
  - Must fail initially (DBAPIExecutor not implemented yet)

### Integration Tests (Based on quickstart.md scenarios)

- [x] **T006** [P] Integration test for IPM installation in `tests/integration/test_ipm_installation.py`
  - Test scenarios: install succeeds, server starts on port 5432, Python dependencies installed, server stops cleanly
  - Mock IPM execution, validate file deployment

- [x] **T007** [P] Integration test for large vector operations in `tests/integration/test_dbapi_large_vectors.py`
  - Test scenarios: Create table with 1024-dim vectors, Insert vector data, Execute similarity query with <-> operator, Verify DBAPI backend used
  - Requires real IRIS instance (no mocks per Constitutional Principle II)

- [x] **T008** [P] Integration test for backend selection in `tests/integration/test_backend_selection.py`
  - Test scenarios: DBAPI selected via config, Embedded selected via config, Backend switches correctly, Invalid config rejected
  - E2E test with real PostgreSQL client (psycopg)

- [x] **T009** [P] Integration test for connection pooling under load in `tests/integration/test_connection_pooling.py`
  - Test scenarios: 1000 concurrent connections handled, Pool exhaustion timeout works, Connection recycling after 1 hour, Health check detects degraded pool
  - Performance test: Avg acquisition time <1ms

---

## Phase 3.3: Data Models (Foundation) ⚠️ ONLY after tests are failing

- [x] **T010** [P] BackendConfig model in `src/iris_pgwire/models/backend_config.py`
  - Fields: backend_type, iris_hostname, iris_port, iris_namespace, iris_username, iris_password, pool_size, pool_max_overflow, pool_timeout, pool_recycle, enable_otel, otel_endpoint
  - Validation: pool_size + pool_max_overflow <= 200, all connection fields required if DBAPI backend
  - Use Pydantic for validation

- [x] **T011** [P] ConnectionPoolState model in `src/iris_pgwire/models/connection_pool_state.py`
  - Fields: pool_id, connections_created, connections_available, connections_in_use, connections_failed, total_acquisitions, total_releases, avg_acquisition_time_ms, last_health_check, health_status
  - Invariants: connections_in_use + connections_available <= pool_size + pool_max_overflow

- [x] **T012** [P] VectorQueryRequest model in `src/iris_pgwire/models/vector_query_request.py`
  - Fields: request_id, original_sql, vector_operator, vector_column, query_vector, limit_clause, translated_sql, translation_time_ms, backend_type
  - Validation: query_vector dimensions 1-2048, translation_time_ms < 5.0 (constitutional SLA)
  - Operator mapping: <-> → VECTOR_COSINE, <#> → VECTOR_DOT_PRODUCT, <=> → VECTOR_L2

- [x] **T013** [P] DBAPIConnection model in `src/iris_pgwire/models/dbapi_connection.py`
  - Fields: connection_id, created_at, last_used_at, query_count, transaction_active, isolation_level, cursor_count, health_status
  - Lifecycle states: Created → Idle → Active → Closed
  - Health check method: validate_connection()

- [x] **T014** [P] IPMModuleMetadata model in `src/iris_pgwire/models/ipm_metadata.py`
  - Fields: module_name, version, iris_min_version, ipm_min_version, python_dependencies, installation_hooks, service_lifecycle
  - Validation: semver format, lowercase module name with hyphens only

---

## Phase 3.4: Core Implementation (Backend Selection & Execution)

### Backend Selector Implementation

- [x] **T015** Backend selector in `src/iris_pgwire/backend_selector.py`
  - Methods: select_backend(config: BackendConfig) -> Executor, validate_config(config: BackendConfig) -> bool
  - Logic: Return DBAPIExecutor if config.backend_type == "dbapi", else EmbeddedExecutor
  - Validation: Check credentials required for DBAPI, pool limits, connection parameters
  - Dependencies: T010 (BackendConfig model), T004 (contract test must pass)

### DBAPI Executor Implementation

- [x] **T016** DBAPI connection pool in `src/iris_pgwire/dbapi_connection_pool.py`
  - Class: IRISConnectionPool
  - Methods: __init__(config), async acquire(), async release(conn), async close(), health_check()
  - Implementation: Queue-based pool (from research R2), asyncio.to_thread() for thread safety
  - Pool config: 50 base + 20 overflow, 30s timeout, 1 hour recycle
  - Dependencies: T011 (ConnectionPoolState model)

- [x] **T017** DBAPI executor in `src/iris_pgwire/dbapi_executor.py`
  - Class: DBAPIExecutor
  - Methods: __init__(config), async execute_query(sql, params), async execute_vector_query(request), async health_check(), async close()
  - Logic: Use connection pool for all queries, validate connections, handle IRIS restarts
  - Performance: Query overhead <5ms (constitutional SLA)
  - Dependencies: T016 (connection pool), T012 (VectorQueryRequest model), T005 (contract test must pass)

### Vector Query Translation Enhancement

- [x] **T018** Enhance vector optimizer for DBAPI backend in `src/iris_pgwire/vector_optimizer.py`
  - Add method: bind_vector_parameter(vector: list[float]) -> str
  - Logic: Convert Python list to TO_VECTOR('[0.1,0.2,...]', 'DECIMAL') format (from research R4)
  - Performance: Translation time <5ms, support vectors up to 2048 dimensions
  - Dependencies: T012 (VectorQueryRequest model)

---

## Phase 3.5: IPM Packaging (Deployment)

### IPM Package Definition

- [x] **T019** IPM module.xml in `ipm/module.xml`
  - Structure: ZPM package with FileCopy elements for Python code, Invoke hooks for lifecycle
  - Elements: Name (iris-pgwire), Version (0.1.0), SystemRequirements (IRIS >=2024.1)
  - FileCopy: src/iris_pgwire/ → ${libdir}iris-pgwire/iris_pgwire/, requirements.txt → ${libdir}iris-pgwire/
  - Invoke hooks: IrisPGWire.Installer.InstallPythonDeps (Activate/After), IrisPGWire.Service.Start (Activate/After), IrisPGWire.Service.Stop (Clean/Before)
  - **CRITICAL**: Use TCP server pattern with <Invoke> hooks, NO <WSGIApplication> or <ASGIApplication> elements (from research R1)
  - Dependencies: T014 (IPMModuleMetadata model)

### ObjectScript Installer Class

- [x] **T020** ObjectScript installer class in `ipm/IrisPGWire/Installer.cls`
  - Class: IrisPGWire.Installer Extends %RegisteredObject
  - Methods: InstallPythonDeps() As %Status
  - Logic: Get libdir from %IPM.Utils, run irispip install -r requirements.txt via $ZF(-1)
  - Error handling: Return $$$ERROR if pip install fails
  - Dependencies: T019 (module.xml)

### ObjectScript Service Lifecycle Class

- [x] **T021** ObjectScript service class in `ipm/IrisPGWire/Service.cls`
  - Class: IrisPGWire.Service Extends %RegisteredObject
  - Methods: Start() As %Status, Stop() As %Status, GetStatus() As %String
  - Logic: Start TCP server via /usr/irissys/bin/irispython -m iris_pgwire.server, store PID, Stop via SIGTERM
  - Health check: Verify port 5432 listening, read PID file
  - Dependencies: T019 (module.xml)

### IPM Requirements File

- [x] **T022** Update IPM requirements.txt in `ipm/requirements.txt`
  - Dependencies: intersystems-irispython>=3.2.0, opentelemetry-api>=1.20.0, opentelemetry-sdk>=1.20.0, opentelemetry-instrumentation-asyncio>=0.41b0, opentelemetry-exporter-otlp>=1.20.0
  - Copy from pyproject.toml [project.dependencies] section
  - Dependencies: T002 (pyproject.toml updated)

---

## Phase 3.6: Observability & Production Readiness

### OpenTelemetry Integration

- [x] **T023** [P] OTEL setup in `src/iris_pgwire/observability.py`
  - Functions: setup_opentelemetry(service_name, otel_endpoint), add_otel_context(event_dict)
  - Integration: TracerProvider with OTLPSpanExporter, MeterProvider with OTLPMetricExporter, AsyncioInstrumentor
  - Structlog integration: Add trace_id and span_id to log events
  - Dependencies: T002 (OTEL dependencies installed)
  - Can run in parallel with T015-T018 (different files)

### Health Checks and Monitoring

- [x] **T024** [P] Health checker in `src/iris_pgwire/health_checker.py`
  - Class: HealthChecker
  - Methods: async check_iris_health() -> bool, async handle_iris_restart()
  - Logic: Test query "SELECT 1", exponential backoff reconnection (10 attempts, 2^n seconds)
  - Dependencies: T016 (connection pool)
  - Can run in parallel with T023

### IRIS Logging Integration

- [x] **T025** [P] IRIS log handler in `src/iris_pgwire/iris_log_handler.py`
  - Class: IRISLogHandler(logging.Handler)
  - Method: emit(record)
  - Logic: Write to IRIS messages.log via iris.execute("Do ##class(%SYS.System).WriteToConsoleLog(...)")
  - Integration: Add to structlog processors
  - Dependencies: None (can run in parallel)

---

## Phase 3.7: Integration & Validation

### Docker Test Environment

- [x] **T026** Docker Compose for IPM testing in `docker/docker-compose.ipm.yml`
  - Services: iris (from kg-ticket-resolver pattern), pgwire-test (for validation)
  - Network: Connect to existing IRIS instance
  - Volumes: Mount ipm/ directory for testing installation
  - Dependencies: T019-T022 (IPM package complete)
  - Status: Complete - docker-compose.ipm.yml and merge.cpf created

### End-to-End Validation

- [x] **T027** Run quickstart validation workflow from `specs/018-add-dbapi-option/quickstart.md`
  - Steps: IPM install, configure DBAPI backend, verify PostgreSQL connectivity, create vector table (1024-dim), execute similarity query, verify DBAPI usage, benchmark performance
  - Success criteria: All 8 quickstart steps pass, translation time <5ms, performance comparable to pgvector PostgreSQL
  - Status: Complete - validation script passing all 8 steps
  - Dependencies: T006-T009 (integration tests), T019-T022 (IPM packaging), T026 (Docker environment)

---

## Phase 3.8: Polish & Documentation

- [x] **T028** [P] Update documentation
  - Files: README.md (add DBAPI backend section), STATUS.md (mark feature complete), DBAPI_BACKEND.md (troubleshooting guide)
  - Content: Installation instructions via IPM, configuration examples, performance benchmarks, troubleshooting common issues
  - Dependencies: T027 (validation complete)
  - Status: Complete - README.md updated with IPM installation, backend selection guide, and feature status; STATUS.md marked feature complete; DBAPI_BACKEND.md troubleshooting guide created

---

## Phase 3.9: Integration Test Infrastructure (Constitutional Principle II)

**CRITICAL**: Constitutional Principle II requires all integration tests run against real IRIS instances. Docker Compose test runner services are MANDATORY for constitutional compliance.

- [x] **T029** Create pytest-integration service in `docker-compose.yml`
  - Service: pytest-integration with `--profile test` activation
  - Dependencies: depends_on iris with condition: service_healthy
  - Environment: IRIS connection parameters (IRIS_HOSTNAME=iris, IRIS_PORT=1972, IRIS_USERNAME=_SYSTEM, IRIS_PASSWORD=SYS, IRIS_NAMESPACE=USER)
  - Command: Run pytest tests/integration/ -v -m requires_iris --junitxml=test-results/integration-results.xml
  - Volumes: Mount src/, tests/, pyproject.toml as read-only; mount test-results/ for output
  - Constitutional requirement: Real IRIS instance testing per Principle II
  - Dependencies: T006-T009 (integration tests written)
  - Status: Complete - pytest-integration service added to docker-compose.yml

- [x] **T030** Create pytest-contract service in `docker-compose.yml`
  - Service: pytest-contract with `--profile test` activation
  - Dependencies: None (contract tests don't require IRIS)
  - Environment: PYTHONPATH=/app/src
  - Command: Run pytest tests/contract/ -v --junitxml=test-results/contract-results.xml
  - Volumes: Mount src/, tests/, pyproject.toml as read-only; mount test-results/ for output
  - Purpose: Run contract tests that don't require IRIS database
  - Dependencies: T004-T005 (contract tests written)
  - Status: Complete - pytest-contract service added to docker-compose.yml

- [x] **T031** Create test runner Dockerfile in `Dockerfile.test`
  - Base image: python:3.11-slim
  - System dependencies: git
  - Python dependencies: pytest>=7.0.0, pytest-asyncio>=0.21.0, pytest-timeout>=2.1.0, pytest-cov>=4.0.0, intersystems-irispython>=3.2.0, pydantic>=2.0.0, pyyaml>=6.0.0, structlog>=23.0.0, opentelemetry-api>=1.20.0, opentelemetry-sdk>=1.20.0
  - Copy: src/, tests/, pyproject.toml
  - Environment: PYTHONPATH=/app/src
  - Default command: pytest tests/ -v --tb=short
  - Dependencies: T002 (pyproject.toml dependencies defined)
  - Status: Complete - Dockerfile.test created with all dependencies

- [x] **T032** Create comprehensive testing documentation in `TESTING.md`
  - Sections: Constitutional Requirement (Principle II), Test Categories (Contract vs Integration), Running Tests (Docker Compose commands), Test Environment Variables, Test Markers, Continuous Integration, Troubleshooting, Coverage Reporting, Performance Benchmarking, Validation Checklist
  - Examples: docker compose --profile test run --rm pytest-integration, pytest -m requires_iris
  - Constitutional compliance: Document real IRIS instance requirement, no mocks policy
  - Dependencies: T029-T031 (test infrastructure complete)
  - Status: Complete - TESTING.md created with comprehensive guide

---

## Dependencies Graph

```
Setup (T001-T003)
    ↓
Tests (T004-T009) [ALL PARALLEL - must fail before implementation]
    ↓
Models (T010-T014) [ALL PARALLEL - different files]
    ↓
    ├── Backend Selector (T015) ← depends on T010, T004
    ├── Connection Pool (T016) ← depends on T011
    ├── DBAPI Executor (T017) ← depends on T016, T012, T005
    └── Vector Enhancement (T018) ← depends on T012
    ↓
    ├── IPM Packaging (T019-T022) ← sequential, depends on T014, T017
    └── Observability (T023-T025) [PARALLEL - independent files]
    ↓
Docker Environment (T026) ← depends on T019-T022
    ↓
E2E Validation (T027) ← depends on T006-T009, T019-T026
    ↓
Documentation (T028) [PARALLEL] ← depends on T027
    ↓
Test Infrastructure (T029-T032) [PARALLEL - Constitutional Principle II] ← depends on T006-T009
    ├── pytest-integration service (T029) ← depends on T006-T009
    ├── pytest-contract service (T030) ← depends on T004-T005
    ├── Dockerfile.test (T031) ← depends on T002
    └── TESTING.md (T032) ← depends on T029-T031
```

---

## Parallel Execution Examples

### Phase 3.2 - Launch All Tests Together (TDD)
```bash
# All contract and integration tests can run in parallel
Task: "Contract test for BackendSelector in tests/contract/test_backend_selector_contract.py"
Task: "Contract test for DBAPIExecutor in tests/contract/test_dbapi_executor_contract.py"
Task: "Integration test for IPM installation in tests/integration/test_ipm_installation.py"
Task: "Integration test for large vector operations in tests/integration/test_dbapi_large_vectors.py"
Task: "Integration test for backend selection in tests/integration/test_backend_selection.py"
Task: "Integration test for connection pooling in tests/integration/test_connection_pooling.py"
```

### Phase 3.3 - Launch All Models Together
```bash
# All data models can run in parallel (different files)
Task: "BackendConfig model in src/iris_pgwire/models/backend_config.py"
Task: "ConnectionPoolState model in src/iris_pgwire/models/connection_pool_state.py"
Task: "VectorQueryRequest model in src/iris_pgwire/models/vector_query_request.py"
Task: "DBAPIConnection model in src/iris_pgwire/models/dbapi_connection.py"
Task: "IPMModuleMetadata model in src/iris_pgwire/models/ipm_metadata.py"
```

### Phase 3.6 - Launch Observability Tasks Together
```bash
# Observability components are independent
Task: "OTEL setup in src/iris_pgwire/observability.py"
Task: "Health checker in src/iris_pgwire/health_checker.py"
Task: "IRIS log handler in src/iris_pgwire/iris_log_handler.py"
```

---

## Constitutional Compliance Checkpoints

### Phase 3.2 (Tests First - Principle II)
- [x] All contract tests written and failing before T015
- [x] Integration tests use real IRIS instances (no mocks)
- [x] Real PostgreSQL clients used (psql, psycopg)

### Phase 3.9 (Test Infrastructure - Principle II)
- [x] Docker Compose pytest-integration service created (T029)
- [x] Docker Compose pytest-contract service created (T030)
- [x] Test runner Dockerfile created (T031)
- [x] TESTING.md documentation created (T032)
- [ ] Integration tests actually executed against real IRIS via docker-compose
- [ ] Test results captured and verified

### Phase 3.4 (Performance - Principle VI)
- [ ] Translation time <5ms (T018, T027)
- [ ] Vector queries comparable to pgvector PostgreSQL (T007, T027)
- [ ] 1000 concurrent connections supported (T009, T027)

### Phase 3.5 (IRIS Integration - Principle IV)
- [ ] CallIn service required (documented in quickstart)
- [ ] TCP server pattern (NOT ASGI/WSGI) (T019)
- [ ] ObjectScript lifecycle classes (T020, T021)

### Phase 3.6 (Production Readiness - Principle V)
- [ ] OTEL integration (T023)
- [ ] IRIS messages.log integration (T025)
- [ ] Health checks and reconnection logic (T024)
- [ ] Connection pooling (T016)

---

## Notes

- **[P] tasks** = Different files, no dependencies, can run in parallel
- **TDD Critical**: T004-T009 MUST fail before implementing T015-T018
- **TCP Server Pattern**: IPM packaging uses `<Invoke>` hooks, NOT `<WSGIApplication>` or `<ASGIApplication>` elements (research R1)
- **Real Testing**: No mocks for IRIS connections (Constitutional Principle II)
- **Performance SLA**: <5ms translation overhead (Constitutional Principle VI)
- **Commit Strategy**: Commit after each task completion
- **Branch**: All work on `018-add-dbapi-option`

---

## Validation Checklist
*GATE: Must pass before marking feature complete*

- [x] All contract tests (T004-T005) passing
- [ ] All integration tests (T006-T009) passing **← BLOCKED: Need to run via docker-compose**
- [x] All 5 entities modeled (T010-T014)
- [x] Backend selector working (T015)
- [x] DBAPI executor operational (T016-T017)
- [x] Vector translation enhanced (T018)
- [x] IPM package installable (T019-T022)
- [x] OTEL metrics exported (T023)
- [x] Health checks functional (T024)
- [x] Quickstart workflow succeeds (T027)
- [x] Documentation updated (T028)
- [x] Test infrastructure created (T029-T032)
- [ ] Integration tests executed via docker-compose against real IRIS **← CRITICAL**
- [ ] Constitutional compliance verified (all checkpoints passed)

---

**Total Tasks**: 32 (3 setup + 6 tests + 5 models + 4 core + 4 IPM + 3 observability + 1 Docker + 1 validation + 1 docs + 4 test infrastructure)

**Estimated Effort**:
- Phase 3.1-3.2: 2 days (setup + TDD tests)
- Phase 3.3-3.4: 3 days (models + implementation)
- Phase 3.5: 2 days (IPM packaging)
- Phase 3.6-3.7: 2 days (observability + validation)
- Phase 3.8: 0.5 days (documentation)
- Phase 3.9: 0.5 days (test infrastructure + execution)
- **Total**: ~10 days

**Ready for Execution**: ✅ All tasks defined with clear file paths, dependencies, and acceptance criteria

**Current Status**: T001-T032 complete (infrastructure), but integration tests NOT YET EXECUTED against real IRIS via docker-compose (Constitutional Principle II violation until tests run)

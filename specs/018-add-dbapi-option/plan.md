# Implementation Plan: DBAPI Backend Option with IPM Packaging

**Branch**: `018-add-dbapi-option` | **Date**: 2025-10-05 | **Spec**: [spec.md](./spec.md)
**Input**: Feature specification from `/specs/018-add-dbapi-option/spec.md`

## Execution Flow (/plan command scope)
```
1. Load feature spec from Input path
   → ✅ Loaded spec.md
2. Fill Technical Context (scan for NEEDS CLARIFICATION)
   → ✅ Context filled from spec and clarifications
3. Fill the Constitution Check section based on the content of the constitution document.
   → ✅ Constitution v1.2.1 principles applied
4. Evaluate Constitution Check section below
   → ✅ No violations - feature aligns with all constitutional principles
5. Execute Phase 0 → research.md
   → ✅ COMPLETE (research.md created)
6. Execute Phase 1 → contracts, data-model.md, quickstart.md, CLAUDE.md
   → ✅ COMPLETE (all artifacts created)
7. Re-evaluate Constitution Check section
   → ✅ PASS (no new violations introduced)
8. Plan Phase 2 → Describe task generation approach (DO NOT create tasks.md)
   → ✅ COMPLETE (approach documented below)
9. STOP - Ready for /tasks command
   → PENDING
```

**IMPORTANT**: The /plan command STOPS at step 8. Phases 2-4 are executed by other commands:
- Phase 2: /tasks command creates tasks.md
- Phase 3-4: Implementation execution (manual or via tools)

## Summary

Add DBAPI backend option to IRIS PGWire server to enable large vector support (>1000 dimensions) using the intersystems-irispython DBAPI SDK. Package entire module as a background TCP server process deployable via InterSystems Package Manager (IPM) for one-command installation. This enables PostgreSQL client connectivity to IRIS with production-grade vector similarity queries comparable to pgvector PostgreSQL performance.

**Technical Approach**: Dual backend architecture with configuration-driven selection between embedded Python (`iris.sql.exec()`) and DBAPI (`intersystems-irispython.connect()`) execution paths. TCP server process managed via IPM lifecycle hooks (`<Invoke>` start/stop methods). OTEL observability integration for production monitoring.

## Technical Context

**Language/Version**: Python 3.11+ (matching IRIS embedded Python environment)
**Primary Dependencies**:
- intersystems-irispython (DBAPI SDK for large vector support)
- asyncio (TCP server framework)
- iris module (embedded Python execution - existing)
- IRIS OTEL integration (observability)
**Storage**: InterSystems IRIS (vector embeddings, SQL data)
**Testing**: pytest, real PostgreSQL clients (psql, psycopg), IRIS instances
**Target Platform**: InterSystems IRIS 2024.1+ (OTEL capability, IPM lifecycle hooks)
**Project Type**: Single (backend server with dual execution paths)
**Performance Goals**:
- Vector queries: Comparable to pgvector PostgreSQL performance
- Query translation: <5ms overhead (constitutional requirement)
- Connection pooling: 1000 max connections, pool size 50
**Constraints**:
- IRIS 2024.1+ required (OTEL capability, IPM lifecycle hooks)
- IPM v0.7.2+ required
- CallIn service enabled (constitutional requirement for embedded Python)
- OTEL enabled for observability
- Port 5432 available for TCP server binding
**Scale/Scope**:
- Medium production load (1000 concurrent connections)
- Vector datasets ≥100K for HNSW benefits (constitutional guidance)
- Enterprise IRIS deployments

## Constitution Check
*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

**Principle I: Protocol Fidelity** ✅ PASS
- Feature maintains PostgreSQL wire protocol compliance
- DBAPI backend provides alternative SQL execution path without protocol changes
- No protocol deviations introduced

**Principle II: Test-First Development** ✅ PASS
- E2E testing with real PostgreSQL clients required (psql, psycopg)
- Real IRIS instances mandatory (no mocks)
- Integration tests for DBAPI backend vs embedded Python paths

**Principle III: Phased Implementation** ✅ PASS
- Feature builds on completed P0-P4 phases
- Adds to P5 (vector support) with DBAPI backend option
- No disruption to phase sequence

**Principle IV: IRIS Integration** ✅ PASS
- CallIn service requirement maintained (merge.cpf)
- Embedded Python path preserved (`iris.sql.exec()`)
- DBAPI path uses intersystems-irispython standard authentication
- Dual-path architecture supports both integration patterns
- Terminology: "DBAPI backend" clearly distinguished from "embedded Python backend"

**Principle V: Production Readiness** ✅ PASS
- OTEL integration for observability (FR-015)
- IRIS messages.log for centralized logging
- Authentication via DBAPI standard capabilities
- Connection pooling (1000 max / 50 pool)
- SSL/TLS inherited from existing server implementation

**Principle VI: Vector Performance Requirements** ✅ PASS
- Performance target: Comparable to pgvector PostgreSQL (clarification)
- HNSW indexing supported via DBAPI backend
- Dataset scale awareness documented (≥100K for benefits)
- Constitutional 5ms translation overhead maintained

**Security Requirements** ✅ PASS
- Authentication via intersystems-irispython DBAPI (standard)
- TLS encryption inherited from existing implementation
- Input validation maintained in protocol layer

**Performance Standards** ✅ PASS
- Query translation <5ms overhead (constitutional)
- 1000 concurrent connections supported (clarified)
- 50 connection pool size (medium production load)
- Vector query performance: pgvector baseline (clarified)

**Development Workflow** ✅ PASS
- Phase gates maintained
- Integration tests against real IRIS
- Performance benchmarks required for vector operations

**Conclusion**: ✅ NO VIOLATIONS - Feature fully aligns with constitutional principles

## Project Structure

### Documentation (this feature)
```
specs/018-add-dbapi-option/
├── spec.md              # Feature specification (COMPLETE)
├── plan.md              # This file (/plan command output)
├── research.md          # Phase 0 output (IN PROGRESS)
├── data-model.md        # Phase 1 output (PENDING)
├── quickstart.md        # Phase 1 output (PENDING)
├── contracts/           # Phase 1 output (PENDING)
└── tasks.md             # Phase 2 output (/tasks command - NOT created by /plan)
```

### Source Code (repository root)
```
src/iris_pgwire/
├── __init__.py
├── server.py              # TCP server entry point (asyncio)
├── protocol.py            # PostgreSQL wire protocol (existing)
├── iris_executor.py       # Embedded Python backend (existing)
├── dbapi_executor.py      # NEW: DBAPI backend implementation
├── backend_selector.py    # NEW: Configuration-driven backend selection
├── vector_optimizer.py    # Vector query optimization (existing)
├── types.py               # Type system and OID mapping (existing)
└── auth.py               # SCRAM authentication (existing)

ipm/
├── module.xml            # NEW: IPM package metadata
├── Installer.cls         # NEW: ObjectScript installer class
├── Service.cls           # NEW: ObjectScript service lifecycle (start/stop)
└── requirements.txt      # Python dependencies for IPM install

tests/
├── contract/             # Contract tests (existing framework)
│   ├── test_dbapi_backend_contract.py       # NEW: DBAPI interface contract
│   └── test_backend_selector_contract.py    # NEW: Backend selection contract
├── integration/          # Integration tests (existing framework)
│   ├── test_dbapi_large_vectors.py          # NEW: >1000 dim vector tests
│   ├── test_ipm_installation.py             # NEW: IPM install validation
│   └── test_tcp_server_lifecycle.py         # NEW: TCP server start/stop validation
└── unit/                 # Unit tests (existing)
    ├── test_dbapi_executor.py               # NEW: DBAPI executor logic
    └── test_backend_selector.py             # NEW: Backend selection logic

docker/
├── docker-compose.ipm.yml     # NEW: IPM deployment test environment
└── merge.cpf                  # CallIn service config (existing)
```

**Structure Decision**: Single project structure maintained. New DBAPI backend components added alongside existing embedded Python backend. IPM packaging files added in dedicated `ipm/` directory with ObjectScript classes for lifecycle management. Testing framework extended with DBAPI-specific tests while preserving existing test structure.

**Critical Clarification**: iris-pgwire is a **TCP server** (port 5432 PostgreSQL wire protocol), NOT an ASGI/WSGI web application. IPM deployment uses `<Invoke>` lifecycle hooks to start/stop the background TCP server process, NOT `<WSGIApplication>` or `<ASGIApplication>` elements.

## Phase 0: Outline & Research

**Unknowns Extraction** (from Technical Context and remaining spec clarifications):

1. ✅ **RESOLVED**: Performance targets → Comparable to pgvector PostgreSQL
2. ✅ **RESOLVED**: Authentication method → intersystems-irispython DBAPI capabilities
3. ✅ **RESOLVED**: Logging strategy → IRIS messages.log + OTEL
4. ✅ **RESOLVED**: Connection pooling → 1000 max / 50 pool
5. ⚠️ **OUTSTANDING**: Vector validation timing (FR-016) - Deferred to implementation
6. ⚠️ **OUTSTANDING**: Memory error handling - Deferred to implementation
7. ⚠️ **OUTSTANDING**: IRIS restart handling - Deferred to implementation
8. 🔍 **RESEARCH NEEDED**: IPM module.xml format and ASGI registration
9. 🔍 **RESEARCH NEEDED**: intersystems-irispython DBAPI connection pooling patterns
10. 🔍 **RESEARCH NEEDED**: IRIS OTEL integration API

**Research Tasks**:

### R1: IPM Module Structure and TCP Server Lifecycle
**Question**: How to structure module.xml for TCP server deployment via IPM lifecycle hooks?
**Reference**: https://community.intersystems.com/post/running-wsgi-applications-ipm
**Output**: module.xml template, `<Invoke>` hook patterns, ObjectScript start/stop methods
**Decision**: Use TCP server pattern with lifecycle hooks (NOT WSGI/ASGI)

### R2: intersystems-irispython DBAPI Connection Pooling
**Question**: How to implement connection pooling with intersystems-irispython for 1000 concurrent connections / 50 pool size?
**Reference**: PyPI intersystems-irispython package documentation
**Output**: Connection pool implementation pattern, thread safety considerations

### R3: IRIS OTEL Integration API
**Question**: How to integrate with IRIS OpenTelemetry capability for observability?
**Reference**: IRIS 2024.1+ OTEL documentation
**Output**: OTEL integration patterns, logging/metrics/tracing APIs

### R4: DBAPI Large Vector Parameter Binding
**Question**: How does intersystems-irispython handle vector parameters >1000 dimensions?
**Known Issue**: External DBAPI connections may have limitations vs embedded Python
**Output**: Vector parameter passing patterns, workarounds if needed

### R5: TCP Server Lifecycle with IRIS
**Question**: How does TCP server process lifecycle integrate with IRIS startup/shutdown via IPM hooks?
**Edge Case**: IRIS restart handling while TCP server running
**Output**: Health check patterns, reconnection strategies, graceful shutdown via ObjectScript methods

**Output File**: Creating research.md now...

## Phase 2: Task Planning Approach
*This section describes what the /tasks command will do - DO NOT execute during /plan*

**Task Generation Strategy**:

### 1. Contract Test Tasks (TDD - Tests First)
- **Input**: contracts/backend-selector-contract.md, contracts/dbapi-executor-contract.md
- **Output**: Failing contract tests
- **Tasks**:
  - [P] Create test_backend_selector_contract.py (5 test cases)
  - [P] Create test_dbapi_executor_contract.py (7 test cases)
- **Priority**: HIGHEST (constitutional Principle II - Test-First Development)

### 2. Data Model Tasks (Foundation)
- **Input**: data-model.md entity definitions
- **Output**: Python dataclasses/Pydantic models
- **Tasks**:
  - [P] Create BackendConfig model with validation
  - [P] Create ConnectionPoolState model
  - [P] Create VectorQueryRequest model
  - Create config.yaml schema and loader
- **Dependency**: Must complete before backend implementation

### 3. Backend Implementation Tasks (Core Logic)
- **Input**: Contracts, research findings
- **Output**: Working backend selector and DBAPI executor
- **Tasks**:
  - Create backend_selector.py (select_backend, validate_config)
  - Create dbapi_executor.py (execute_query, connection pooling)
  - Create connection_pool.py (IRISConnectionPool, async acquire/release)
- **Dependency**: Requires data models, must pass contract tests

### 4. IPM Packaging Tasks (Deployment)
- **Input**: Research R1 (IPM module structure - TCP server pattern)
- **Output**: IPM installable package with lifecycle hooks
- **Tasks**:
  - Create ipm/module.xml (ZPM package with `<Invoke>` hooks, NO ASGI elements)
  - Create IrisPGWire.Installer.cls (ObjectScript - InstallPythonDeps method)
  - Create IrisPGWire.Service.cls (ObjectScript - Start/Stop methods for TCP server)
  - Update requirements.txt with new dependencies (intersystems-irispython, opentelemetry-*)
- **Dependency**: Backend implementation complete
- **Critical**: Use TCP server pattern, NOT WSGI/ASGI application elements

### 5. Observability Tasks (Production Readiness)
- **Input**: Research R3 (OTEL integration)
- **Output**: OpenTelemetry instrumentation
- **Tasks**:
  - Create observability.py (setup_opentelemetry)
  - Enhance PerformanceMonitor with OTEL metrics
  - Add OTEL context to structlog
  - Create health check endpoint
- **Dependency**: Can run in parallel with backend implementation

### 6. Integration Test Tasks (E2E Validation)
- **Input**: quickstart.md workflow
- **Output**: E2E tests validating complete installation
- **Tasks**:
  - Create test_ipm_installation.py (IPM install/uninstall)
  - Create test_dbapi_large_vectors.py (>1000 dim vectors)
  - Create test_backend_selection.py (DBAPI vs Embedded switching)
  - Create test_connection_pooling.py (1000 concurrent connections)
- **Dependency**: Requires IPM packaging + backend implementation

### 7. Documentation Tasks (Knowledge Transfer)
- **Input**: All implementation artifacts
- **Output**: Updated documentation
- **Tasks**:
  - Update README.md with DBAPI backend instructions
  - Update STATUS.md with feature completion
  - Create DBAPI_BACKEND.md (troubleshooting guide)
- **Dependency**: Implementation complete

**Ordering Strategy**:

1. **Phase A - Foundation** (TDD Tests + Data Models):
   - [P] Contract test tasks (can run in parallel)
   - [P] Data model tasks (can run in parallel)
   - Estimated: 8 tasks

2. **Phase B - Implementation** (Core Logic):
   - Backend selector (depends on models)
   - DBAPI executor (depends on models, selector)
   - Connection pool (depends on executor)
   - Estimated: 6 tasks

3. **Phase C - Production** (Packaging + Observability):
   - [P] IPM packaging (parallel with observability)
   - [P] OTEL instrumentation (parallel with packaging)
   - Estimated: 7 tasks

4. **Phase D - Validation** (Integration Tests):
   - IPM installation tests
   - Large vector tests
   - Connection pooling tests
   - Estimated: 4 tasks

5. **Phase E - Documentation** (Final):
   - Update all documentation
   - Estimated: 3 tasks

**Estimated Total**: 28 tasks (8 foundation + 6 implementation + 7 production + 4 validation + 3 docs)

**Parallel Execution Markers**:
- [P] indicates tasks that can run in parallel (no shared file dependencies)
- Sequential tasks ordered by dependency graph

**Performance Gates**:
- All tasks must maintain constitutional <5ms translation overhead
- Vector operations must be comparable to pgvector PostgreSQL
- Connection pool must handle 1000 concurrent connections

**IMPORTANT**: This phase is executed by the /tasks command, NOT by /plan

## Progress Tracking
*This checklist is updated during execution flow*

**Phase Status**:
- [x] Phase 0: Research complete (/plan command)
- [x] Phase 1: Design complete (/plan command)
- [x] Phase 2: Task planning complete (/plan command - approach described)
- [ ] Phase 3: Tasks generated (/tasks command)
- [ ] Phase 4: Implementation complete
- [ ] Phase 5: Validation passed

**Gate Status**:
- [x] Initial Constitution Check: PASS
- [x] Post-Design Constitution Check: PASS
- [x] All NEEDS CLARIFICATION resolved (5 clarifications answered)
- [x] Complexity deviations documented (none - no violations)

**Artifacts Generated**:
- [x] research.md (Phase 0)
- [x] data-model.md (Phase 1)
- [x] contracts/backend-selector-contract.md (Phase 1)
- [x] contracts/dbapi-executor-contract.md (Phase 1)
- [x] quickstart.md (Phase 1)
- [x] CLAUDE.md updated (Phase 1)
- [ ] tasks.md (Phase 2 - /tasks command)

---

## Summary

**Planning Complete**: ✅ Ready for /tasks command

**Key Decisions**:
1. DBAPI backend using intersystems-irispython (large vector support)
2. Queue-based asyncio connection pool (50+20 connections)
3. Python OTEL SDK for cross-platform observability
4. **IPM packaging with TCP server lifecycle hooks (NOT ASGI/WSGI web application)**
5. Performance target: Comparable to pgvector PostgreSQL
6. ObjectScript classes for service management (IrisPGWire.Installer, IrisPGWire.Service)

**Constitutional Compliance**: ✅ All principles satisfied, no violations

**Next Command**: `/tasks` - Generate implementation tasks from design artifacts

---

*Based on Constitution v1.2.1 - See `.specify/memory/constitution.md`*

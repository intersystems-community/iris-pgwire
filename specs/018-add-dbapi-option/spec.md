# Feature Specification: DBAPI Backend Option with IPM Packaging

**Feature Branch**: `018-add-dbapi-option`
**Created**: 2025-10-05
**Status**: Draft
**Input**: User description: "add DBAPI option as the SQL back end for PGWire server. This code path would use the intersystems-irispython connect() and dbapi sdk (see pypi page of that package for details) as the server-side sql connection. This gets us large vector support. Also, specify that the entire module is packaged as an IPM module with TCP server lifecycle management, that anyone can install - see https://community.intersystems.com/post/running-wsgi-applications-ipm"

## Execution Flow (main)
```
1. Parse user description from Input
   → Feature adds DBAPI backend option and IPM packaging
2. Extract key concepts from description
   → Actors: System administrators, developers installing PGWire
   → Actions: Select backend, install via IPM, query large vectors
   → Data: Vector embeddings, SQL queries
   → Constraints: IRIS compatibility, TCP server lifecycle management
3. For each unclear aspect:
   → Performance targets for large vector operations marked
   → Migration path from existing deployment marked
4. Fill User Scenarios & Testing section
   → Installation scenario, backend selection, vector query execution
5. Generate Functional Requirements
   → Each requirement testable via IPM installation or query execution
6. Identify Key Entities
   → Backend configuration, IPM module metadata, vector queries
7. Run Review Checklist
   → WARN: Performance targets need clarification
   → WARN: Migration strategy needs clarification
8. Return: SUCCESS (spec ready for planning)
```

---

## ⚡ Quick Guidelines
- ✅ Focus on WHAT users need and WHY
- ❌ Avoid HOW to implement (no tech stack, APIs, code structure)
- 👥 Written for business stakeholders, not developers

### Section Requirements
- **Mandatory sections**: Must be completed for every feature
- **Optional sections**: Include only when relevant to the feature
- When a section doesn't apply, remove it entirely (don't leave as "N/A")

---

## User Scenarios & Testing *(mandatory)*

### Primary User Story

A system administrator wants to install the PGWire server on their IRIS instance to enable PostgreSQL client connectivity. They need the installation to be simple (one-command via IPM), and they need the server to support large vector operations (>1000 dimensions) for their AI/ML workloads. The PGWire server runs as a background TCP server process (port 5432) managed by IRIS lifecycle hooks. Once installed, application developers should be able to connect using standard PostgreSQL clients and execute vector similarity queries without any special configuration.

### Acceptance Scenarios

1. **Given** an IRIS instance with IPM installed, **When** the administrator runs the IPM install command for iris-pgwire, **Then** the PGWire TCP server process is deployed and starts listening on port 5432

2. **Given** the PGWire server is installed via IPM, **When** a PostgreSQL client connects to the configured endpoint, **Then** the connection is established and the client can execute SQL queries against IRIS

3. **Given** a table contains vector embeddings with more than 1000 dimensions, **When** a client executes a vector similarity query (e.g., ORDER BY embedding <-> query_vector), **Then** the query returns results correctly using the DBAPI backend

4. **Given** the PGWire server is configured with DBAPI backend, **When** a client executes a standard SQL query (SELECT, INSERT, UPDATE, DELETE), **Then** the query is executed against IRIS and results are returned in PostgreSQL wire protocol format

5. **Given** the IPM module is installed, **When** the administrator updates the configuration to select DBAPI backend, **Then** the server uses the DBAPI connection for all SQL operations

6. **Given** this is the initial release with IPM packaging, **When** an administrator installs iris-pgwire via IPM, **Then** the installation completes successfully without migration concerns (no prior deployments exist)

### Edge Cases

- What happens when the DBAPI backend encounters a vector operation that exceeds available memory?
  - System SHOULD gracefully degrade when large vector operations exceed available memory by catching IRIS memory errors, logging memory pressure to IRIS messages.log with OTEL span context, and returning PostgreSQL-compatible error message to client (e.g., "ERROR: insufficient memory for vector operation"). Server MUST NOT crash. Connection pool SHOULD mark affected connection as stale for recycling.

- How does the system handle IRIS instance restarts while the PGWire TCP server process is running?
  - System MUST implement exponential backoff reconnection strategy (per research R5): On connection failure, close all pooled DBAPI connections, attempt reconnection with exponential backoff (10 attempts, 2^n seconds delay, max 1024 seconds). Health checker MUST test IRIS availability via "SELECT 1" query before declaring pool healthy. After 10 failed attempts, system SHOULD return "server unavailable" error to new client connections while continuing background reconnection attempts. Existing client connections SHOULD receive clear error message and opportunity to retry.

- What happens when multiple PostgreSQL clients attempt to connect simultaneously?
  - System handles up to 1000 concurrent connections using a pool of 50 DBAPI connections; excess connections queued or rejected with clear error message

- How does the system behave when the IPM installation is initiated on an IRIS version that doesn't support IPM lifecycle hooks?
  - System MUST fail installation with a clear error message indicating minimum IRIS version required (2024.1+)

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: System MUST provide a configuration option to select between DBAPI backend and embedded Python backend for SQL execution

- **FR-002**: System MUST support installation via InterSystems Package Manager (IPM) using a single command (e.g., `zpm "install iris-pgwire"`)

- **FR-003**: System MUST deploy as a TCP server process managed by IRIS lifecycle hooks (see FR-012) when installed through IPM

- **FR-004**: System MUST support vector embeddings with dimensions exceeding 1000 when using DBAPI backend

- **FR-005**: System MUST establish SQL connections using the DBAPI interface when DBAPI backend is selected

- **FR-006**: System MUST automatically install required Python dependencies specified in requirements.txt during IPM installation and include all necessary files (Python code, configuration) for complete deployment

- **FR-007**: System MUST support standard PostgreSQL client connections (psql, psycopg, JDBC, etc.) regardless of backend selection

- **FR-008**: System MUST execute SQL queries (SELECT, INSERT, UPDATE, DELETE, DDL) correctly through the DBAPI connection

- **FR-009**: System MUST translate PostgreSQL wire protocol messages to IRIS SQL syntax and execute via DBAPI when DBAPI backend is active

- **FR-010**: System MUST return query results in PostgreSQL wire protocol format to connected clients

- **FR-011**: IPM module MUST register startup/shutdown hooks to manage the TCP server process lifecycle during installation (see FR-012 for lifecycle hook details)

- **FR-012**: IPM module MUST register startup/shutdown hooks via `<Invoke>` elements (per FR-003) to manage TCP server process lifecycle: Start method launches server on port 5432 during Activate phase, Stop method gracefully terminates server during Clean phase

- **FR-013**: System MUST support uninstallation via IPM that cleanly removes all installed components

- **FR-014**: System MUST support up to 1000 concurrent PostgreSQL client connections with a DBAPI connection pool size of 50 for medium production load scenarios

- **FR-015**: System MUST log all connection events and errors to IRIS messages.log and integrate with IRIS OpenTelemetry (OTEL) capability for observability

- **FR-016**: System MUST validate vector dimensions match schema requirements at query execution time to align with PostgreSQL pgvector behavior. Validation occurs when the DBAPI executor processes VectorQueryRequest (before executing VECTOR_COSINE/VECTOR_DOT_PRODUCT/VECTOR_L2 functions). Invalid dimensions (mismatch with schema or out of range 1-2048) MUST return PostgreSQL-compatible error message to client without server crash.

- **FR-017**: System MUST handle IRIS authentication using the same authentication capabilities provided by the intersystems-irispython DBAPI client (supports username/password, connection strings, and integrated authentication per DBAPI standard)

- **FR-018**: System MUST execute large vector similarity queries (>1000 dimensions) using DBAPI backend with performance within 2× of pgvector PostgreSQL baseline (target: <20ms P95 latency for 100K vectors with HNSW indexing per constitutional Principle VI dataset scale thresholds). Performance measured at ≥100K vector scale where HNSW provides documented 4-10× improvement over sequential scan.

- **FR-019**: System MUST provide Docker Compose test runner services (pytest-integration and pytest-contract) for executing integration tests against real IRIS instances per Constitutional Principle II (Test-First Development). Test runner MUST depend on IRIS service health check, pass IRIS connection parameters via environment variables, and output JUnit XML results. This is MANDATORY for constitutional compliance - integration tests cannot be run manually or via mocks.

### Key Entities *(include if feature involves data)*

- **Backend Configuration**: Represents the choice between DBAPI and embedded Python execution paths, including connection parameters and performance settings. Used by the server initialization process to establish the SQL execution strategy.

- **IPM Module Metadata**: Contains package name, version, dependencies, installation instructions, and lifecycle hook configuration. Defines how the PGWire TCP server integrates with IRIS via IPM.

- **TCP Server Process**: Background process started via IPM lifecycle hooks that binds to port 5432 and handles incoming PostgreSQL wire protocol connections. Managed by IRIS start/stop commands.

- **Vector Query Request**: Represents a PostgreSQL wire protocol query containing vector similarity operations (e.g., <->, <#>, <=>) that must be translated to IRIS VECTOR functions when executed via DBAPI.

- **DBAPI Connection**: Represents the connection established using the DBAPI interface. Maintains session state, transaction context, and provides SQL execution interface to IRIS.

---

## Review & Acceptance Checklist
*GATE: Automated checks run during main() execution*

### Content Quality
- [x] No implementation details (languages, frameworks, APIs)
- [x] Focused on user value and business needs
- [x] Written for non-technical stakeholders
- [x] All mandatory sections completed

### Requirement Completeness
- [x] No [NEEDS CLARIFICATION] markers remain (all resolved: FR-016 validation timing specified, edge cases clarified)
- [x] Requirements are testable and unambiguous (except marked items)
- [x] Success criteria are measurable (performance target: comparable to pgvector PostgreSQL)
- [x] Scope is clearly bounded
- [x] Dependencies and assumptions identified
- [x] Test infrastructure requirement documented (FR-019)
- [ ] Integration tests executed against real IRIS via docker-compose **← CRITICAL**

---

## Execution Status
*Updated by main() during processing*

- [x] User description parsed
- [x] Key concepts extracted
- [x] Ambiguities marked
- [x] User scenarios defined
- [x] Requirements generated (FR-001 through FR-019)
- [x] Entities identified
- [x] Test infrastructure requirement added (FR-019)
- [ ] Review checklist passed (blocked on integration test execution)

---

## Clarifications

### Session 2025-10-05

- Q: What are the performance targets for large vector similarity queries (>1000 dimensions)? → A: Compare to pgvector PostgreSQL performance
- Q: How should the DBAPI backend authenticate to IRIS? → A: Same authentication as intersystems DBAPI client uses
- Q: Where should the PGWire server log connection events and errors? → A: IRIS messages.log and use IRIS OTEL capability
- Q: What are the connection pooling limits and concurrent connection handling requirements? → A: 1000 max connections, pool size 50 - Medium production load
- Q: What is the migration path for existing PGWire deployments upgrading to the IPM-packaged version? → A: Not applicable - This is initial release, no existing deployments

---

## Dependencies and Assumptions

### Dependencies
- IRIS version 2024.1 or higher (required for OTEL capability and lifecycle hooks)
- InterSystems Package Manager (IPM) v0.7.2 or higher installed
- intersystems-irispython package available via pip
- IRIS instance configured to allow embedded Python execution
- IRIS OpenTelemetry (OTEL) capability available (IRIS 2024.1+ manages OTEL export; iris-pgwire adds trace context to logs)
- Network access for pip to download Python dependencies during installation
- Docker and Docker Compose for running integration tests against real IRIS instances (Constitutional Principle II requirement)

### Assumptions
- Users have administrative access to IRIS instance for IPM installation
- IRIS instance has sufficient memory to handle large vector operations
- PostgreSQL clients support PostgreSQL wire protocol version 3.0+
- DBAPI backend provides equivalent functionality to embedded Python backend for all supported SQL operations
- The TCP server process will be managed by IRIS lifecycle hooks but runs as a background irispython process

### Terminology Notes

**IRIS Integration Terminology** (per constitution v1.2.1, Principle IV):
- **"IRIS native"** refers to the low-level globals SDK for accessing IRIS multivalue B+-tree storage engine, NOT external DBAPI driver connections
- **"External DBAPI connections"** or **"IRIS DBAPI driver"** refers to TCP connections using intersystems-irispython package (this feature's implementation)
- **"Embedded Python"** refers to execution via `irispython` command with direct `import iris` and `iris.sql.exec()` calls

This distinction is important when discussing vector parameter binding and performance characteristics. External DBAPI connections have different limitations than embedded Python execution within the IRIS process.

---

## Clarification Questions for Stakeholders

**Resolved in Session 2025-10-05** (see Clarifications section above):
1. ✅ **Migration Path**: Not applicable - initial release
2. ✅ **Performance Targets**: Compare to pgvector PostgreSQL
3. ✅ **Connection Limits**: 1000 max connections, pool size 50
4. ✅ **Logging Strategy**: IRIS messages.log + OTEL integration
5. ✅ **Authentication**: Use intersystems-irispython DBAPI authentication

**Resolved in Analysis Phase** (2025-10-05):
6. ✅ **Vector Validation**: Query execution time validation (see FR-016 - aligns with PostgreSQL pgvector behavior)

7. ✅ **Error Handling**: Graceful degradation with PostgreSQL-compatible error messages, no server crash, connection marked stale for recycling (see Edge Cases)

8. ✅ **IRIS Restart Handling**: Exponential backoff reconnection (10 attempts, 2^n seconds), health checks via "SELECT 1", background reconnection with client error messages (see Edge Cases, research R5)

---

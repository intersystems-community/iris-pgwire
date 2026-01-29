# Feature Specification: Fix Connection Pool AttributeError

**Feature Branch**: `038-fix-attribute-error`  
**Created**: 2026-01-29  
**Status**: Draft  
**Input**: User description: "fix docs/bugs/iris-pgwire-attribute-error-1.2.31.md"

## Clarifications

### Session 2026-01-29
- Q: Should attributes be added to the model or calculated locally? → A: Add missing attributes (`is_overflow`, `idle_seconds`) to the `DBAPIConnection` model.
- Q: How should logging ensure stability if attributes are missing? → A: Use safe attribute access (`getattr(obj, 'attr', default)`) in all pool logging.
- Q: How should idle_seconds be implemented in the model? → A: Add `idle_seconds` as a computed property (`@property`) on the `DBAPIConnection` model.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Stable Server Startup (Priority: P1)

As a system operator, I want the server to start reliably without encountering property-related errors in the connection management layer so that the database bridge is available for application traffic.

**Why this priority**: This is a critical fix as the server currently fails to boot, blocking all functionality.

**Independent Test**: Can be fully tested by starting the server and verifying it reaches the "Ready For Query" state without crashing.

**Acceptance Scenarios**:

1. **Given** a standard server configuration, **When** the server is started, **Then** the connection pool initializes successfully and no `AttributeError` is raised.
2. **Given** an active connection pool, **When** a connection is recycled due to age or inactivity, **Then** the event is logged successfully without crashing the background process.

---

### Edge Cases

- **Concurrent Failures**: If multiple connections fail to initialize simultaneously, does the logging logic remain stable?
- **Stale Metadata**: If a connection object is modified but the logging logic is not updated, how does the system prevent a fatal crash? (Should use safe attribute access or default values).

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: System MUST successfully initialize the connection pool without encountering "missing attribute" errors.
- **FR-002**: System MUST use valid property names and safe attribute access (e.g., `getattr`) when logging connection lifecycle events to prevent fatal crashes if metadata is missing.
- **FR-003**: System MUST provide a computed `idle_seconds` property on the connection model that calculates duration based on the current UTC time and the last usage timestamp.
- **FR-004**: System MUST ensure that connection metadata (is_overflow, idle_seconds) is explicitly defined in the DBAPIConnection Pydantic model to guarantee availability during logging.

### Key Entities *(include if feature involves data)*

- **DatabaseConnection**: A managed resource representing a single connection to the IRIS database. Attributes include identity, last usage timestamp, health status, overflow status (`is_overflow`), and calculated idle duration (`idle_seconds`).
- **ConnectionPool**: The manager responsible for the lifecycle of DatabaseConnections.

## Assumptions & Dependencies

- **Assumption**: The underlying connection driver provides stable timestamps for usage tracking.
- **Assumption**: Logging frameworks in use support structured context or safe string formatting.
- **Dependency**: The server must be capable of reloading or restarting to apply these fixes.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: 100% of server initialization attempts succeed without encountering `AttributeError` in the connection pool.
- **SC-002**: Connection lifecycle logs (recycling, removal) generate successfully without triggering exceptions.
- **SC-003**: Server remains operational after connection recycling events.

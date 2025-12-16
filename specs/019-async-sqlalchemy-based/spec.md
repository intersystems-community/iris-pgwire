# Feature Specification: Async SQLAlchemy Support via PGWire

**Feature Branch**: `019-async-sqlalchemy-based`
**Created**: 2025-10-08
**Status**: Draft
**Input**: User description: "async sqlalchemy based on research findings and what we have learned so far"

## Execution Flow (main)
```
1. Parse user description from Input
   → Feature: Enable async SQLAlchemy ORM usage with IRIS via PGWire protocol
2. Extract key concepts from description
   → Actors: Python developers using FastAPI async framework
   → Actions: Create async database sessions, execute async queries, use async ORM
   → Data: IRIS database accessed via PostgreSQL wire protocol
   → Constraints: Must maintain IRIS-specific features (VECTOR types, INFORMATION_SCHEMA)
3. For each unclear aspect:
   → Performance targets: [NEEDS CLARIFICATION: What async query throughput is required?]
   → Compatibility scope: [NEEDS CLARIFICATION: Which async frameworks must be supported?]
4. Fill User Scenarios & Testing section
   → Primary: Developer creates async engine and executes queries
   → Secondary: Developer uses async ORM models with IRIS vector types
5. Generate Functional Requirements
   → Each requirement based on research findings (psycopg async, get_async_dialect_cls)
6. Identify Key Entities
   → AsyncEngine, AsyncSession, async dialect class
7. Run Review Checklist
   → [NEEDS CLARIFICATION] markers present for performance and compatibility
   → Implementation details minimized (framework names only for context)
8. Return: SUCCESS (spec ready for planning with clarifications noted)
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

### For AI Generation
When creating this spec from a user prompt:
1. **Mark all ambiguities**: Use [NEEDS CLARIFICATION: specific question] for any assumption you'd need to make
2. **Don't guess**: If the prompt doesn't specify something (e.g., "login system" without auth method), mark it
3. **Think like a tester**: Every vague requirement should fail the "testable and unambiguous" checklist item
4. **Common underspecified areas**:
   - User types and permissions
   - Data retention/deletion policies
   - Performance targets and scale
   - Error handling behaviors
   - Integration requirements
   - Security/compliance needs

---

## Clarifications

### Session 2025-10-08
- Q: What minimum performance threshold is required for async query execution? → A: Async must match sync performance (within 10% latency) for single queries
- Q: Which async Python frameworks must be validated for compatibility? → A: FastAPI only (most common async web framework)

---

## User Scenarios & Testing *(mandatory)*

### Primary User Story
A Python developer building an async FastAPI web application needs to connect to IRIS database using the async/await pattern. They want to use SQLAlchemy's async ORM capabilities to define models, execute queries, and manage database sessions asynchronously. The connection must work through the PostgreSQL wire protocol (PGWire) while maintaining access to IRIS-specific features like VECTOR types and INFORMATION_SCHEMA queries.

**Current State**: Sync SQLAlchemy works via `iris+psycopg://` connection string, but async SQLAlchemy fails with "AwaitRequired" errors despite dialect having `is_async = True` flag set.

**Desired State**: Developer can use `create_async_engine("iris+psycopg://localhost:5432/USER")` and execute async queries with full IRIS feature support.

### Acceptance Scenarios

1. **Given** an async Python application with SQLAlchemy installed, **When** developer creates async engine with `iris+psycopg://` connection string, **Then** engine creation succeeds without errors and returns proper async engine instance

2. **Given** an async SQLAlchemy engine connected to IRIS via PGWire, **When** developer executes simple async query using `await conn.execute(text("SELECT 1"))`, **Then** query executes successfully and returns expected results without "AwaitRequired" errors

3. **Given** an async SQLAlchemy session with IRIS vector table, **When** developer executes vector similarity query using async ORM patterns, **Then** query is translated to IRIS vector functions and returns results asynchronously

4. **Given** an async SQLAlchemy engine, **When** developer performs bulk insert using async executemany pattern, **Then** records are inserted efficiently without falling back to synchronous loop execution

5. **Given** sync and async SQLAlchemy implementations, **When** developer runs benchmark comparing performance, **Then** async implementation executes single queries within 10% latency of sync performance

### Edge Cases

- What happens when async engine is used with synchronous code paths (detect and provide clear error)?
- How does system handle connection pooling in async mode (proper async pool class)?
- What happens when IRIS-specific features (VECTOR types) are used in async queries (maintain compatibility)?
- How does system behave when psycopg is installed in sync-only mode (detect and guide user)?
- What happens during transaction management in async context (proper async commit/rollback)?

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: System MUST support async SQLAlchemy engine creation using `iris+psycopg://` connection string format
- **FR-002**: System MUST execute async queries without raising "AwaitRequired" exceptions when using `create_async_engine()`
- **FR-003**: System MUST properly resolve to async dialect variant when SQLAlchemy detects async context
- **FR-004**: System MUST maintain all IRIS-specific features (VECTOR types, INFORMATION_SCHEMA queries, IRIS functions) in async mode
- **FR-005**: System MUST use proper async connection pool class for async engine instances
- **FR-006**: System MUST support async transaction management (async commit, async rollback)
- **FR-007**: System MUST execute bulk inserts efficiently in async mode without falling back to synchronous loops
- **FR-008**: System MUST work with psycopg async connection objects (AsyncConnection) when in async mode
- **FR-009**: System MUST provide clear error messages when async dependencies are missing or misconfigured
- **FR-010**: System MUST allow developers to use both sync and async dialects in same application (different connection strings)
- **FR-011**: System MUST support async ORM model definitions and async session operations
- **FR-012**: System MUST handle async cursor operations for IRIS-specific metadata queries
- **FR-013**: System MUST execute async queries with latency within 10% of sync SQLAlchemy performance for single-query operations
- **FR-014**: System MUST validate compatibility with FastAPI async framework (benchmark and integration test required)

### Key Entities *(include if feature involves data)*

- **Async Engine**: Represents asynchronous database connection pool configured for IRIS via PGWire protocol. Manages async connection lifecycle and session creation.

- **Async Session**: Provides async context for ORM operations. Manages transaction boundaries asynchronously and maintains IRIS-specific type handling.

- **Async Dialect Class**: SQLAlchemy dialect implementation that combines IRIS database features with psycopg async transport. Inherits from both IRISDialect (IRIS features) and PGDialectAsync_psycopg (async PostgreSQL protocol).

- **DBAPI Module**: psycopg library in async mode providing PostgreSQL wire protocol transport. Must be properly configured for async operation.

---

## Research Findings Summary *(context for implementation)*

**Root Cause Identified**: psycopg3 driver supports both sync and async modes through the same module. SQLAlchemy's dialect resolution logic defaults to sync mode unless explicitly told to resolve to async variant via `get_async_dialect_cls()` class method.

**Key Discovery**: Setting `is_async = True` on dialect is insufficient. SQLAlchemy needs explicit method override to resolve to async dialect class that properly inherits from `PGDialectAsync_psycopg`.

**Sync Working State**: Current `IRISDialect_psycopg` works perfectly with sync SQLAlchemy:
```python
# Sync works ✅
engine = create_engine("iris+psycopg://localhost:5432/USER")
with engine.connect() as conn:
    result = conn.execute(text("SELECT 1"))
```

**Async Failing State**: Same dialect fails with async SQLAlchemy despite `is_async = True`:
```python
# Async fails ❌ (AwaitRequired error)
engine = create_async_engine("iris+psycopg://localhost:5432/USER")
async with engine.connect() as conn:
    result = await conn.execute(text("SELECT 1"))
```

**Solution Pattern** (from research): Implement `get_async_dialect_cls()` to return proper async variant:
- Must inherit from both `IRISDialect` (IRIS features) and `PGDialectAsync_psycopg` (async transport)
- Must properly configure DBAPI module in async mode
- Must maintain all IRIS-specific overrides (on_connect, isolation levels, executemany)

**Constraint**: Direct inheritance from `PGDialectAsync_psycopg` creates DBAPI configuration challenges. Need to ensure DBAPI is properly established in dynamically created async class.

---

## Review & Acceptance Checklist
*GATE: Automated checks run during main() execution*

### Content Quality
- [x] No implementation details (languages, frameworks, APIs) - Only framework names for context
- [x] Focused on user value and business needs - Enables modern async Python frameworks
- [x] Written for non-technical stakeholders - User scenarios describe developer workflows
- [x] All mandatory sections completed

### Requirement Completeness
- [x] No [NEEDS CLARIFICATION] markers remain
- [x] Requirements are testable and unambiguous - Acceptance scenarios provide test cases
- [x] Success criteria are measurable - Performance benchmarks can validate
- [x] Scope is clearly bounded - Async SQLAlchemy support via existing PGWire protocol
- [x] Dependencies and assumptions identified - Research findings document current state

---

## Execution Status
*Updated by main() during processing*

- [x] User description parsed - "async sqlalchemy based on research findings"
- [x] Key concepts extracted - Async ORM, psycopg async mode, dialect resolution
- [x] Ambiguities marked - Performance targets and framework compatibility scope
- [x] User scenarios defined - Primary story covers async developer workflow
- [x] Requirements generated - 14 functional requirements with 2 needing clarification
- [x] Entities identified - AsyncEngine, AsyncSession, AsyncDialect, DBAPI
- [x] Review checklist passed - 2 clarifications needed before implementation

---

## Next Steps

1. **Clarify** performance requirements (FR-013) and framework compatibility scope (FR-014)
2. **Run** `/clarify` command to address ambiguities through targeted questions
3. **Proceed** to `/plan` phase once clarifications are resolved
4. **Validate** implementation with benchmark comparing sync vs async performance

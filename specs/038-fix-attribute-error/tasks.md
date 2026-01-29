# Tasks: Fix Connection Pool AttributeError

## Implementation Strategy

This feature focuses on restoring server stability by fixing critical `AttributeError` crashes in the `IRISConnectionPool`. We will follow a TDD approach by first creating a reproduction test that confirms the crash, then updating the Pydantic models and pool logic to resolve the issue.

1.  **MVP (Phase 3)**: Update the `DBAPIConnection` model and `IRISConnectionPool` logging to ensure error-free server startup.

## Phase 1: Setup

- [X] T001 Verify branch `038-fix-attribute-error` and environment setup in specs/038-fix-attribute-error/
- [X] T002 Verify Python 3.11+ environment and dependencies (pydantic, structlog)

## Phase 2: Foundational

- [X] T003 [P] Create reproduction unit test demonstrating the AttributeError in tests/unit/test_dbapi_connection_stability.py

## Phase 3: Stable Server Startup (Priority: P1) [US1]

**Goal**: Ensure the server starts reliably without encountering property-related errors in the connection management layer.
**Independent Test**: `pytest tests/unit/test_dbapi_connection_stability.py` passes after fix.

- [X] T004 [P] [US1] Add `is_overflow` boolean field to DBAPIConnection model in src/iris_pgwire/models/dbapi_connection.py
- [X] T005 [P] [US1] Implement computed `idle_seconds` property in DBAPIConnection model in src/iris_pgwire/models/dbapi_connection.py
- [X] T006 [US1] Update IRISConnectionPool logging to use safe `getattr` access in src/iris_pgwire/dbapi_connection_pool.py
- [X] T007 [US1] Fix incorrect logging message in _create_connection in src/iris_pgwire/dbapi_connection_pool.py
- [X] T008 [US1] Verify fix by running reproduction test in tests/unit/test_dbapi_connection_stability.py

## Phase 4: Polish & Cross-Cutting

- [X] T009 Perform manual server startup verification per quickstart.md
- [X] T010 Verify logging stability during simulated recycling events (trigger by setting PGWIRE_POOL_RECYCLE=1)
- [X] T011 Update project documentation if any metrics behavior changed

## Dependencies

1.  **Phase 3 [US1]** depends on **Phase 2** (reproduction test).

## Parallel Execution Examples

### User Story 1 (Startup Fix)
- T004 and T005 (Model updates) can be performed in parallel as they touch different parts of the same model file.
- T003 (Reproduction test) can be developed while planning the model updates.

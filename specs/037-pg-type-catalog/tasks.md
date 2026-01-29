# Tasks: Implement pg_type Catalog Emulation

## Implementation Strategy

We will follow an incremental delivery approach, starting with the `pg_type` data model and static type list, followed by the consolidation of catalog routing logic. This ensures that Drizzle ORM migrations (the highest priority) work across all backends.

1.  **MVP (Phase 3)**: Complete `pg_type` emulation and enable it for `DBAPIExecutor` and `IRISExecutor`.
2.  **Incremental (Phase 4)**: Ensure generic type discovery and empty extension result handling.

## Phase 1: Setup

- [X] T001 Initialize feature directory and verify environment in specs/037-pg-type-catalog/
- [X] T002 Verify Python 3.11 environment and required dependencies (structlog, pydantic)

## Phase 2: Foundational

- [X] T003 [P] Ensure OIDGenerator supports standard OIDs (11 for pg_catalog) in src/iris_pgwire/catalog/oid_generator.py
- [X] T004 Define PgType dataclass and static standard type list in src/iris_pgwire/catalog/pg_type.py
- [X] T005 Update CatalogRouter to support handle_catalog_query interface in src/iris_pgwire/catalog/catalog_router.py

## Phase 3: Drizzle ORM Migration (Priority: P1) [US1]

**Goal**: Enable Drizzle ORM to introspect IRIS types without "Table not found" errors.
**Independent Test**: `psql` query for `pg_type` where `typname = 'int4'` returns OID 23.

- [X] T006 [US1] Create failing integration test for Drizzle-style introspection in tests/integration/test_catalog_emulation.py
- [X] T007 [P] [US1] Implement PgTypeEmulator with standard types and unknown type mapping (FR-010) in src/iris_pgwire/catalog/pg_type.py
- [X] T008 [US1] Implement basic filtering by `typname` in CatalogRouter.handle_catalog_query
- [X] T009 [US1] Move and consolidate catalog interception logic into CatalogRouter
- [X] T010 [US1] Integrate backends: call handle_catalog_query from DBAPIExecutor and IRISExecutor
- [X] T011 [US1] Verify passing integration test and refine implementation

## Phase 4: Generic Type Discovery (Priority: P2) [US2]

**Goal**: Support broader client compatibility for type mapping.
**Independent Test**: `SELECT * FROM pg_type` returns 21 standard rows.

- [X] T012 [US2] Create failing unit test for comprehensive type list verification in tests/unit/test_pg_type_emulation.py
- [X] T013 [P] [US2] Implement pg_extension interception returning empty results in src/iris_pgwire/catalog/catalog_router.py
- [X] T014 [US2] Implement case-insensitive matching for pg_catalog schema prefix in src/iris_pgwire/catalog/catalog_router.py

## Phase 5: Polish & Cross-Cutting

- [X] T015 Verify <5ms overhead for catalog interceptions via structlog metrics
- [X] T016 Ensure strict_single_connection mode does not bypass catalog emulation
- [X] T017 Final verification with Drizzle ORM `drizzle-kit push` scenario

## Dependencies

1.  **Phase 3 [US1]** depends on **Phase 2**.
2.  **Phase 4 [US2]** depends on **Phase 3 [US1]**.

## Parallel Execution Examples

### User Story 1 (Drizzle)
- T007 (PgTypeEmulator) and T009 (Logic move) can start in parallel.
- Integration tests (T006) should be created before implementation tasks.

### User Story 2 (Generic Discovery)
- T013 (pg_extension) and T014 (Case-insensitivity) can be developed in parallel.

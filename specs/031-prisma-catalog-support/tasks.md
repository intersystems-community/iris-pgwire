# Tasks: Prisma Catalog Support

**Feature Branch**: `031-prisma-catalog-support`
**Input**: Design documents from `/specs/031-prisma-catalog-support/`
**Prerequisites**: plan.md (required), research.md, data-model.md, contracts/, quickstart.md
**Generated**: 2025-12-24

---

## Summary

This task list implements PostgreSQL system catalog emulation (`pg_class`, `pg_attribute`, `pg_constraint`, `pg_index`, etc.) to enable Prisma ORM database introspection against IRIS PGWire.

**User Stories Mapped**:
- **US1**: Core catalog tables (FR-001 to FR-005) - pg_class, pg_attribute, pg_constraint, pg_index, pg_namespace
- **US2**: Supporting catalogs and query support (FR-006 to FR-012) - pg_type, pg_attrdef, array params, JOINs
- **US3**: Data mapping and schema integration (FR-013 to FR-015) - Schema mapping, type OIDs, stable OIDs
- **US4**: Prisma introspection validation (FR-016 to FR-018) - End-to-end Prisma db pull

---

## Phase 1: Setup

- [x] T001 Create catalog module directory structure at src/iris_pgwire/catalog/
- [x] T002 [P] Create catalog module __init__.py at src/iris_pgwire/catalog/__init__.py
- [x] T003 [P] Create contract test directory at tests/contract/

---

## Phase 2: Foundational (OID Generator - All catalogs depend on this)

**CRITICAL**: OID generator must be complete before any catalog implementation.

- [x] T004 [P] Unit test OID generation basic behavior in tests/unit/test_oid_generator.py
- [x] T005 [P] Unit test OID determinism across instances in tests/unit/test_oid_generator.py
- [x] T006 [P] Unit test OID uniqueness for different objects in tests/unit/test_oid_generator.py
- [x] T007 [P] Unit test well-known namespace OIDs in tests/unit/test_oid_generator.py
- [x] T008 Implement OIDGenerator class per data-model.md in src/iris_pgwire/catalog/oid_generator.py
- [x] T009 Add ObjectIdentity dataclass to src/iris_pgwire/catalog/oid_generator.py
- [x] T010 Verify all unit tests pass for OID generator

---

## Phase 3: US1 - Core Catalog Tables (pg_namespace, pg_class, pg_attribute)

**Goal**: Enable basic table and column discovery for Prisma introspection.
**Independent Test**: Query pg_class and pg_attribute via psql, verify table/column metadata returned.

### pg_namespace (Schema Catalog)

- [x] T011 [P] [US1] Contract test pg_namespace returns public schema in tests/contract/test_catalog_pg_namespace.py
- [x] T012 [US1] Implement PgNamespace dataclass in src/iris_pgwire/catalog/pg_namespace.py
- [x] T013 [US1] Implement PgNamespaceEmulator with static namespaces in src/iris_pgwire/catalog/pg_namespace.py

### pg_class (Table/View Catalog)

- [x] T014 [P] [US1] Contract test pg_class table enumeration in tests/contract/test_catalog_pg_class.py
- [x] T015 [P] [US1] Contract test pg_class OID stability in tests/contract/test_catalog_pg_class.py
- [x] T016 [P] [US1] Contract test pg_class empty schema handling in tests/contract/test_catalog_pg_class.py
- [x] T017 [US1] Implement PgClass dataclass per data-model.md in src/iris_pgwire/catalog/pg_class.py
- [x] T018 [US1] Implement PgClassEmulator.from_iris_table() in src/iris_pgwire/catalog/pg_class.py
- [x] T019 [US1] Implement PgClassEmulator.get_all_tables() querying INFORMATION_SCHEMA.TABLES in src/iris_pgwire/catalog/pg_class.py

### pg_attribute (Column Catalog)

- [x] T020 [P] [US1] Contract test pg_attribute column enumeration in tests/contract/test_catalog_pg_attribute.py
- [x] T021 [P] [US1] Contract test pg_attribute NOT NULL detection in tests/contract/test_catalog_pg_attribute.py
- [x] T022 [P] [US1] Contract test pg_attribute type modifier for VARCHAR in tests/contract/test_catalog_pg_attribute.py
- [x] T023 [US1] Implement PgAttribute dataclass per data-model.md in src/iris_pgwire/catalog/pg_attribute.py
- [x] T024 [US1] Implement TYPE_OID_MAP for IRIS→PostgreSQL type mapping in src/iris_pgwire/catalog/pg_attribute.py
- [x] T025 [US1] Implement PgAttributeEmulator.from_iris_column() in src/iris_pgwire/catalog/pg_attribute.py
- [x] T026 [US1] Implement PgAttributeEmulator.get_columns_for_table() querying INFORMATION_SCHEMA.COLUMNS in src/iris_pgwire/catalog/pg_attribute.py

---

## Phase 4: US1 - Core Catalog Tables (pg_constraint, pg_index)

**Goal**: Enable constraint and index discovery for relationship mapping.
**Independent Test**: Query pg_constraint via psql, verify PK/FK/UNIQUE constraints returned.

### pg_constraint (Constraint Catalog)

- [x] T027 [P] [US1] Contract test pg_constraint primary key discovery in tests/contract/test_catalog_pg_constraint.py
- [x] T028 [P] [US1] Contract test pg_constraint foreign key discovery in tests/contract/test_catalog_pg_constraint.py
- [x] T029 [P] [US1] Contract test pg_constraint unique constraint in tests/contract/test_catalog_pg_constraint.py
- [x] T030 [P] [US1] Contract test pg_constraint composite key in tests/contract/test_catalog_pg_constraint.py
- [x] T031 [US1] Implement PgConstraint dataclass per data-model.md in src/iris_pgwire/catalog/pg_constraint.py
- [x] T032 [US1] Implement PgConstraintEmulator.from_iris_constraint() in src/iris_pgwire/catalog/pg_constraint.py
- [x] T033 [US1] Implement PgConstraintEmulator.get_constraints_for_table() querying TABLE_CONSTRAINTS in src/iris_pgwire/catalog/pg_constraint.py
- [x] T034 [US1] Implement FK column position extraction from KEY_COLUMN_USAGE in src/iris_pgwire/catalog/pg_constraint.py

### pg_index (Index Catalog)

- [x] T035 [P] [US1] Contract test pg_index primary key index in tests/contract/test_catalog_pg_index.py
- [x] T036 [US1] Implement PgIndex dataclass per data-model.md in src/iris_pgwire/catalog/pg_index.py
- [x] T037 [US1] Implement PgIndexEmulator.from_primary_key() generating pg_class + pg_index entries in src/iris_pgwire/catalog/pg_index.py

---

## Phase 5: US2 - Supporting Catalogs and Query Support

**Goal**: Complete catalog coverage and enable complex query patterns.
**Independent Test**: Prisma introspection queries return complete metadata.

### pg_attrdef (Column Defaults)

- [x] T038 [P] [US2] Contract test pg_attrdef returns default values in tests/contract/test_catalog_pg_attrdef.py
- [x] T039 [US2] Implement PgAttrdef dataclass in src/iris_pgwire/catalog/pg_attrdef.py
- [x] T040 [US2] Implement PgAttrdefEmulator.from_iris_default() in src/iris_pgwire/catalog/pg_attrdef.py
- [x] T041 [US2] Implement PgAttrdefEmulator.get_defaults_for_table() querying COLUMN_DEFAULT in src/iris_pgwire/catalog/pg_attrdef.py

### Catalog Router (Query Routing)

- [x] T042 [US2] Implement CatalogRouter.can_handle() detecting pg_catalog queries in src/iris_pgwire/catalog/catalog_router.py
- [x] T043 [US2] Implement CatalogRouter.execute() routing to emulators in src/iris_pgwire/catalog/catalog_router.py
- [x] T044 [US2] Implement SQL query parsing to extract target catalog table in src/iris_pgwire/catalog/catalog_router.py
- [x] T045 [US2] Implement result formatting with PostgreSQL column types in src/iris_pgwire/catalog/catalog_router.py
- [x] T045a [P] [US2] Contract test JOIN queries across pg_class and pg_attribute in tests/contract/test_catalog_router.py

### Array Parameter Handling

- [x] T046 [P] [US2] Contract test array parameter ANY($1) translation in tests/contract/test_catalog_router.py
- [x] T047 [US2] Implement array parameter detection pattern in src/iris_pgwire/catalog/catalog_router.py
- [x] T048 [US2] Implement ANY($1) to IN clause translation in src/iris_pgwire/catalog/catalog_router.py

### regclass Cast Support

- [x] T049 [P] [US2] Contract test ::regclass cast resolution in tests/contract/test_catalog_router.py
- [x] T050 [US2] Implement regclass literal parsing in src/iris_pgwire/catalog/catalog_router.py
- [x] T051 [US2] Implement regclass to OID resolution in src/iris_pgwire/catalog/catalog_router.py

---

## Phase 6: US3 - Integration with iris_executor.py

**Goal**: Route catalog queries from PGWire to catalog emulators.
**Independent Test**: psql queries to pg_catalog return IRIS metadata.

- [x] T052 [US3] Import CatalogRouter in src/iris_pgwire/iris_executor.py
- [x] T053 [US3] Add catalog query interception before IRIS SQL execution in src/iris_pgwire/iris_executor.py
- [x] T054 [US3] Integrate schema_mapper for public↔SQLUser translation in catalog queries
- [x] T055 [US3] Add structlog logging for catalog query execution in src/iris_pgwire/iris_executor.py
- [x] T056 [P] [US3] Integration test catalog queries via PGWire in tests/integration/test_catalog_integration.py

---

## Phase 7: US4 - Prisma E2E Validation

**Goal**: Validate `prisma db pull` works end-to-end with IRIS PGWire.
**Independent Test**: Run quickstart.md validation checklist.

- [ ] T057 [US4] Create test tables per quickstart.md (users, products, orders, order_items)
- [ ] T058 [US4] Integration test Prisma introspection in tests/integration/test_prisma_introspection.py
- [ ] T059 [US4] Verify generated Prisma schema includes all 4 models
- [ ] T060 [US4] Verify Prisma schema includes @id annotations on primary keys
- [ ] T061 [US4] Verify Prisma schema includes @relation annotations on foreign keys
- [ ] T062 [US4] Verify Prisma schema includes correct type mappings (VARCHAR, INTEGER, DECIMAL, etc.)
- [ ] T063 [US4] Verify Prisma schema includes @unique annotations
- [ ] T064 [US4] Verify Prisma schema includes @default annotations
- [ ] T065 [US4] Performance test: introspection <30s for 50-table schema

---

## Phase 8: Polish & Cross-Cutting Concerns

- [x] T066 [P] Add docstrings to all catalog emulator classes
- [ ] T067 [P] Update README.md with Prisma compatibility section
- [x] T068 Verify performance: <5ms catalog query overhead per constitutional limit
- [x] T069 Run full test suite and verify all tests pass
- [ ] T070 Execute quickstart.md validation checklist manually

---

## Dependencies

```
Phase 2 (OID Generator) → blocks all catalog implementations (Phase 3-5)

Phase 3 Dependencies:
  T008 (OIDGenerator) → T012, T013, T017-T019, T023-T026

Phase 4 Dependencies:
  T008 (OIDGenerator) → T031-T037
  T017 (PgClass) → T037 (pg_index needs pg_class entry)

Phase 5 Dependencies:
  T008 (OIDGenerator) → T039-T041
  T012-T026, T031-T037 → T042-T045 (router needs all emulators)

Phase 6 Dependencies:
  T042-T051 (CatalogRouter) → T052-T056

Phase 7 Dependencies:
  T052-T056 (Integration) → T057-T065
```

---

## Parallel Execution Examples

### Phase 2: OID Generator Tests (4 parallel)
```
Task: "Unit test OID generation basic behavior in tests/unit/test_oid_generator.py"
Task: "Unit test OID determinism across instances in tests/unit/test_oid_generator.py"
Task: "Unit test OID uniqueness for different objects in tests/unit/test_oid_generator.py"
Task: "Unit test well-known namespace OIDs in tests/unit/test_oid_generator.py"
```

### Phase 3: pg_class Contract Tests (3 parallel)
```
Task: "Contract test pg_class table enumeration in tests/contract/test_catalog_pg_class.py"
Task: "Contract test pg_class OID stability in tests/contract/test_catalog_pg_class.py"
Task: "Contract test pg_class empty schema handling in tests/contract/test_catalog_pg_class.py"
```

### Phase 4: pg_constraint Contract Tests (4 parallel)
```
Task: "Contract test pg_constraint primary key discovery in tests/contract/test_catalog_pg_constraint.py"
Task: "Contract test pg_constraint foreign key discovery in tests/contract/test_catalog_pg_constraint.py"
Task: "Contract test pg_constraint unique constraint in tests/contract/test_catalog_pg_constraint.py"
Task: "Contract test pg_constraint composite key in tests/contract/test_catalog_pg_constraint.py"
```

---

## Implementation Strategy

### MVP Scope (US1 Only)
For minimal Prisma support, complete:
- Phase 1-2: Setup + OID Generator
- Phase 3: pg_namespace, pg_class, pg_attribute
- Phase 4: pg_constraint (PK only), pg_index
- Phase 6: iris_executor.py integration

This enables basic `prisma db pull` with tables, columns, and primary keys.

### Incremental Delivery
1. **Milestone 1**: OID Generator + pg_namespace (T001-T013)
2. **Milestone 2**: pg_class with table enumeration (T014-T019)
3. **Milestone 3**: pg_attribute with column metadata (T020-T026)
4. **Milestone 4**: pg_constraint with PK/FK (T027-T034)
5. **Milestone 5**: Integration + E2E validation (T052-T065)

---

## Validation Checklist

- [x] All contracts have corresponding tests (T011, T014-T016, T020-T022, T027-T030, T035, T038, T046, T049)
- [x] All entities have model tasks (OIDGenerator, PgNamespace, PgClass, PgAttribute, PgConstraint, PgIndex, PgAttrdef)
- [x] Parallel tasks truly independent (different files, no shared state)
- [x] Each task specifies exact file path
- [x] No task modifies same file as another [P] task
- [x] User story labels applied to all non-setup/non-polish tasks

---

## Task Statistics

| Category | Count |
|----------|-------|
| Total Tasks | 71 |
| Setup (Phase 1) | 3 |
| Foundational (Phase 2) | 7 |
| US1 - Core Catalogs (Phase 3-4) | 27 |
| US2 - Supporting (Phase 5) | 15 |
| US3 - Integration (Phase 6) | 5 |
| US4 - E2E Validation (Phase 7) | 9 |
| Polish (Phase 8) | 5 |
| Parallel [P] Tasks | 27 |

---

*Generated based on plan.md, data-model.md, contracts/, and quickstart.md*

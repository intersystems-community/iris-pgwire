# Feature Specification: Drizzle ORM Support

**Feature Branch**: `032-drizzle-orm-support`
**Created**: 2025-12-25
**Status**: Draft
**Input**: User description: "ensure drizzle orm support"

---

## Overview

Validate and ensure Drizzle ORM compatibility with IRIS PGWire, leveraging the existing catalog emulation (Feature 031) and RETURNING clause support to enable full drizzle-kit introspection and Drizzle ORM CRUD operations.

## Problem Statement

Drizzle ORM is a popular TypeScript ORM that offers a lightweight, SQL-like query builder with type safety. Developers using Drizzle expect to:
1. Introspect existing databases using `drizzle-kit introspect` (generates `schema.ts`)
2. Perform CRUD operations using Drizzle's query builder with RETURNING support
3. Manage migrations using `drizzle-kit push/migrate`

**Current State**: Feature 031 (Prisma Catalog Support) implemented `pg_catalog` tables and `information_schema` views. Feature 031 also implemented RETURNING clause emulation for INSERT/UPDATE/DELETE. Drizzle's PostgreSQL requirements overlap significantly with Prisma's.

**Desired State**: Drizzle ORM works out-of-the-box with IRIS PGWire, including:
- `drizzle-kit introspect` generates accurate TypeScript schemas
- Full CRUD operations with `.returning()` method
- Schema migrations via `drizzle-kit push`

---

## User Scenarios & Testing

### Primary User Story
As a TypeScript developer using Drizzle ORM, I want to connect Drizzle to my IRIS database via PGWire so that I can use Drizzle's type-safe, SQL-like query builder to interact with my IRIS tables.

### Acceptance Scenarios

1. **Given** a Drizzle project configured to connect to IRIS PGWire, **When** running `drizzle-kit introspect`, **Then** Drizzle generates a `schema.ts` file with correct table definitions.

2. **Given** a Drizzle schema connected to IRIS PGWire, **When** executing `db.insert(users).values({...}).returning()`, **Then** the inserted row is returned with all columns including auto-generated IDs.

3. **Given** a Drizzle schema connected to IRIS PGWire, **When** executing `db.select().from(users).where(eq(users.id, 1))`, **Then** the correct row is returned with proper type mapping.

4. **Given** a Drizzle schema connected to IRIS PGWire, **When** executing `db.update(users).set({name: "New"}).where(eq(users.id, 1)).returning()`, **Then** the updated row is returned.

5. **Given** a Drizzle schema connected to IRIS PGWire, **When** executing `db.delete(users).where(eq(users.id, 1)).returning()`, **Then** the deleted row data is returned before deletion.

6. **Given** an IRIS table with various column types, **When** Drizzle introspects the schema, **Then** types are correctly mapped to Drizzle column types (`integer`, `text`, `timestamp`, `boolean`, etc.).

7. **Given** an IRIS table with primary keys and indexes, **When** Drizzle introspects the schema, **Then** the generated schema includes correct primary key and index definitions.

### Edge Cases

- **Empty database**: Introspection succeeds with empty schema
- **Tables with VECTOR columns**: Custom type handling or graceful skip
- **Connection pooling**: Multiple concurrent Drizzle connections work correctly
- **Transaction support**: Drizzle's `db.transaction()` works correctly
- **Prepared statements**: Drizzle's parameterized queries execute correctly

---

## Requirements

### Functional Requirements

#### Drizzle-kit Introspection (drizzle-kit introspect)

- **FR-001**: System MUST respond to Drizzle's `information_schema` queries with accurate table metadata
- **FR-002**: System MUST respond to Drizzle's `pg_catalog` queries (pg_class, pg_attribute, pg_constraint, pg_index, pg_namespace)
- **FR-003**: System MUST return column types that map to valid Drizzle column types
- **FR-004**: System MUST return primary key information in the format Drizzle expects
- **FR-005**: System MUST return index information for `@@index` generation

#### CRUD Operations

- **FR-006**: System MUST support INSERT with `.returning()` via RETURNING clause emulation (implemented in 031)
- **FR-007**: System MUST support UPDATE with `.returning()` via RETURNING clause emulation (implemented in 031)
- **FR-008**: System MUST support DELETE with `.returning()` via pre-capture pattern (implemented in 031)
- **FR-009**: System MUST support parameterized queries (`$1`, `$2`, etc.) with correct type handling

#### Transaction Support

- **FR-010**: System MUST support BEGIN/COMMIT/ROLLBACK for Drizzle transactions
- **FR-011**: System MUST maintain transaction isolation across concurrent queries

#### Type Mapping

- **FR-012**: System MUST map IRIS INTEGER to PostgreSQL int4 (OID 23)
- **FR-013**: System MUST map IRIS VARCHAR to PostgreSQL varchar/text (OID 1043/25)
- **FR-014**: System MUST map IRIS TIMESTAMP to PostgreSQL timestamp (OID 1114)
- **FR-015**: System MUST map IRIS BIGINT to PostgreSQL int8 (OID 20)
- **FR-016**: System MUST map IRIS BIT/BOOLEAN to PostgreSQL boolean (OID 16)
- **FR-017**: System MUST map IRIS DECIMAL/NUMERIC to PostgreSQL numeric (OID 1700)

### Key Entities

- **DrizzleTable**: Generated TypeScript table definition (`pgTable('users', {...})`)
- **DrizzleColumn**: Column definition with type, constraints (`integer('id').primaryKey()`)
- **DrizzleRelation**: Relationship definition for foreign keys
- **DrizzleIndex**: Index definition (`index('idx_name').on(table.column)`)

---

## Success Criteria

1. **Introspection Success**: `drizzle-kit introspect` completes without errors against IRIS PGWire
2. **Schema Accuracy**: Generated `schema.ts` correctly represents IRIS table structures
3. **CRUD Operations**: All `.returning()` operations work correctly (INSERT, UPDATE, DELETE)
4. **Type Mapping**: Common IRIS types map correctly to Drizzle column types
5. **Transactions**: Drizzle's `db.transaction()` works correctly
6. **Performance**: Query performance comparable to direct IRIS SQL access

---

## Existing Capabilities (from Feature 031)

The following capabilities are already implemented and should work with Drizzle:

1. **pg_catalog tables**: pg_class, pg_attribute, pg_constraint, pg_index, pg_namespace, pg_attrdef, pg_type
2. **information_schema views**: tables, columns, table_constraints, key_column_usage, referential_constraints
3. **RETURNING clause emulation**: INSERT/UPDATE/DELETE with RETURNING
4. **Schema mapping**: public ↔ SQLUser translation
5. **Type OID mapping**: Common PostgreSQL types
6. **Parameter handling**: `$N` to `?` placeholder translation

---

## Verification Tasks

1. **Create Drizzle demo project**: Set up a Drizzle project with IRIS PGWire connection
2. **Run introspection**: Execute `drizzle-kit introspect` and verify schema generation
3. **Test CRUD operations**: Verify INSERT/SELECT/UPDATE/DELETE with `.returning()`
4. **Document any gaps**: Identify any Drizzle-specific queries not yet supported
5. **Create test suite**: Add integration tests for Drizzle ORM operations

---

## Dependencies

- Feature 031 (Prisma Catalog Support) - provides catalog emulation and RETURNING support
- Feature 030 (PostgreSQL Schema Mapping) - provides schema name translation

## Assumptions

1. Drizzle uses standard PostgreSQL protocol and catalog queries (similar to Prisma)
2. Existing catalog implementation from Feature 031 covers Drizzle's requirements
3. RETURNING clause emulation works for Drizzle's query builder

## Out of Scope

- Drizzle Studio (GUI tool) compatibility
- Advanced Drizzle features (raw SQL beyond standard operations)
- drizzle-kit push/migrate (schema modification) - read-only introspection first
- Custom Drizzle operators or extensions

---

## Review & Acceptance Checklist

### Content Quality
- [x] No implementation details (languages, frameworks, APIs)
- [x] Focused on user value and business needs
- [x] Written for non-technical stakeholders
- [x] All mandatory sections completed

### Requirement Completeness
- [x] No [NEEDS CLARIFICATION] markers remain
- [x] Requirements are testable and unambiguous
- [x] Success criteria are measurable
- [x] Scope is clearly bounded
- [x] Dependencies and assumptions identified

---

## Execution Status

- [x] User description parsed
- [x] Key concepts extracted
- [x] Ambiguities marked (none - clear scope)
- [x] User scenarios defined
- [x] Requirements generated
- [x] Entities identified
- [x] Review checklist passed

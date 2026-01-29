# Feature Specification: Implement pg_type Catalog Emulation

**Feature Branch**: `037-pg-type-catalog`  
**Created**: 2026-01-29  
**Status**: Draft  
**Input**: User description: "docs/bugs/iris-pgwire-missing-pg-type.md which we have been working on but I want to make more formal process"

## Clarifications

### Session 2026-01-29
- Q: Should pg_type include only static standard types or also discover user types from IRIS? → A: Use a static list of 21 standard types only.
- Q: In which namespace (schema) should the emulated pg_type table reside? → A: pg_catalog (OID 11).
- Q: What OID strategy should be used for the emulated types? → A: Use standard PostgreSQL hardcoded OIDs (e.g., 23 for int4).
- Q: How should the system handle IRIS types that are not in the standard 21-type list? → A: Return a default OID (e.g., 25 for text).
- Q: How should queries targeting pg_extension be handled? → A: Return empty results with standard columns.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Drizzle ORM Migration (Priority: P1)

As a developer using Drizzle ORM, I want to run migrations against my IRIS database so that I can manage my schema programmatically.

**Why this priority**: This is the primary blocker for modern Node.js ORM compatibility.

**Independent Test**: Can be tested by running `drizzle-kit push` or a migration script and verifying it no longer fails with "Table 'PG_CATALOG.PG_TYPE' not found".

**Acceptance Scenarios**:

1. **Given** a Next.js application using Drizzle ORM, **When** running a migration against IRIS via pgwire, **Then** the migration successfully introspects types and executes.
2. **Given** a query for `pg_catalog.pg_type`, **When** filtering for `typname = 'int4'`, **Then** OID 23 is returned.

---

### User Story 2 - Generic Type Discovery (Priority: P2)

As a PostgreSQL-compatible database client, I want to query the system catalogs to understand available data types so that I can correctly format and bind parameters.

**Why this priority**: Essential for broader client compatibility (e.g., asyncpg, Npgsql).

**Independent Test**: Can be tested by running a manual SQL query against `pg_catalog.pg_type` and verifying the presence of standard types (bool, int4, varchar, etc.).

**Acceptance Scenarios**:

1. **Given** a standard PostgreSQL client, **When** querying `pg_type` for all base types, **Then** a list of standard PostgreSQL types with correct OIDs is returned.

---

### Edge Cases

- **Missing Namespace**: How does the system handle queries that don't specify the `pg_catalog` schema? (Should assume `pg_catalog` for `pg_type`).
- **Complex Joins**: How does the system handle a join between `pg_type` and `pg_class`? (Should be routed through `CatalogRouter`).
- **Custom Types**: How are unknown or custom IRIS types handled? (Should default to `varchar` or `text` OID).

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: System MUST emulate the `pg_catalog.pg_type` table using a static list of standard PostgreSQL types in the `pg_catalog` namespace.
- **FR-008**: The `typnamespace` for all emulated types MUST be 11 (pg_catalog).
- **FR-002**: System MUST support the following columns in `pg_type`: `oid`, `typname`, `typnamespace`, `typowner`, `typlen`, `typbyval`, `typtype`, `typcategory`, `typispreferred`, `typisdefined`, `typdelim`, `typrelid`, `typelem`, `typarray`, `typinput`, `typoutput`, `typnotnull`.
- **FR-003**: System MUST provide standard hardcoded PostgreSQL OIDs for emulated types (e.g., bool=16, int4=23, varchar=1043).
- **FR-010**: System MUST map unknown IRIS data types to the default `text` (OID 25) or `varchar` (OID 1043) type OID.
- **FR-011**: System MUST intercept queries for `pg_catalog.pg_extension` and return an empty result set with correct PostgreSQL column metadata.
- **FR-004**: System MUST include support for the `vector` type (OID 16388) for pgvector compatibility.
- **FR-005**: System MUST allow filtering of `pg_type` by `typname` and `typnamespace`.
- **FR-006**: System MUST handle both Simple Query and Extended Protocol queries targeting `pg_type`.
- **FR-007**: System SHALL NOT attempt to discover or return internal IRIS class-based data types in `pg_type`.

### Key Entities *(include if feature involves data)*

- **PgType**: Represents a PostgreSQL data type entry. Attributes include name, OID, namespace, length, and category.

## Assumptions & Dependencies

- **Assumption**: Clients will primarily use standard PostgreSQL OIDs for type recognition.
- **Assumption**: Static emulation of these types is sufficient for Drizzle ORM and most common use cases.
- **Dependency**: Requires `CatalogRouter` to be correctly routing `pg_catalog` queries.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: 100% of Drizzle ORM migration introspection queries against `pg_type` return valid metadata.
- **SC-002**: Queries targeting `pg_catalog.pg_type` return results in under 5ms (excluding network latency).
- **SC-003**: All 21 required base types (bool, bytea, char, name, int8, int2, int4, text, oid, float4, float8, bpchar, varchar, date, time, timestamp, timestamptz, bit, numeric, uuid, vector) are correctly returned.
- **SC-004**: System successfully handles `pg_type` queries regardless of connection mode (embedded or external).

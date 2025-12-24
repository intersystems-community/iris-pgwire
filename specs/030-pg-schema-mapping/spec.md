# Feature Specification: PostgreSQL Schema Mapping for ORM Compatibility

**Feature Branch**: `030-pg-schema-mapping`
**Created**: 2024-12-23
**Status**: Draft
**Input**: User description: "PostgreSQL information_schema compatibility - Map IRIS SQLUser schema to PostgreSQL 'public' schema for ORM introspection tools like Prisma, SQLAlchemy, and other PostgreSQL clients that expect standard schema names"

---

## Problem Statement

PostgreSQL ORM tools and database introspection clients expect tables to reside in the `public` schema by default. IRIS stores user tables in the `SQLUser` schema. This mismatch causes ORM introspection commands to fail:

- **Prisma**: `prisma db pull` fails with serialization errors when querying `public` schema
- **SQLAlchemy**: `metadata.reflect()` returns empty results
- **DBeaver/pgAdmin**: Schema browser shows no user tables under "public"

The underlying issue is simple: queries like `WHERE table_schema = 'public'` return empty results because IRIS uses `SQLUser` as the default schema name.

---

## User Scenarios & Testing

### Primary User Story
As a developer using Prisma ORM, I want to run `prisma db pull` against IRIS PGWire so that I can automatically generate Prisma models from my existing IRIS tables without manual schema configuration.

### Acceptance Scenarios

1. **Given** an IRIS database with tables in SQLUser schema, **When** a PostgreSQL client queries `information_schema.tables WHERE table_schema = 'public'`, **Then** the query returns SQLUser tables with `table_schema` reported as `public`.

2. **Given** a Prisma project configured to connect to IRIS PGWire, **When** the developer runs `prisma db pull`, **Then** Prisma successfully introspects the database and generates a schema.prisma file with model definitions.

3. **Given** a SQLAlchemy application connected to IRIS PGWire, **When** the application calls `metadata.reflect(schema='public')`, **Then** SQLAlchemy discovers and maps all user tables.

4. **Given** a query referencing `public.tablename`, **When** executed via PGWire, **Then** the query resolves to `SQLUser.tablename` and executes successfully.

5. **Given** a query that creates a table without specifying schema, **When** a PostgreSQL client assumes it goes to `public`, **Then** the table is created in SQLUser and accessible via `public.tablename` references.

### Edge Cases

- What happens when a user explicitly references `SQLUser` schema? The query should work unchanged.
- What happens when IRIS system schemas (`%SYS`, `%Library`) are queried? They should remain as-is, not be mapped to `public`.
- How does the system handle case sensitivity? PostgreSQL schema names are case-insensitive by default.
- What if a table actually exists in a schema named `public` in IRIS? (Unlikely but possible)

---

## Requirements

### Functional Requirements

- **FR-001**: System MUST map `public` schema references to `SQLUser` in `information_schema` queries.
- **FR-002**: System MUST return `public` as the `table_schema` value when querying `information_schema.tables` for SQLUser tables.
- **FR-003**: System MUST support `public.tablename` syntax in queries, resolving to `SQLUser.tablename`.
- **FR-004**: System MUST preserve explicit `SQLUser` schema references without modification.
- **FR-005**: System MUST NOT modify references to IRIS system schemas (those starting with `%`).
- **FR-006**: System MUST handle case-insensitive schema name matching (`PUBLIC`, `Public`, `public` all map to configured IRIS schema).
- **FR-007**: System MUST support configurable IRIS schema name via `PGWIRE_IRIS_SCHEMA` environment variable (default: `SQLUser`).
- **FR-008**: System MUST support runtime schema configuration via `configure_schema()` API for programmatic use.

### Non-Functional Requirements

- **NFR-001**: Schema mapping MUST NOT add more than 1ms latency to query processing.
- **NFR-002**: Schema mapping SHOULD work out-of-the-box with default configuration (SQLUser) for standard IRIS deployments.

### Out of Scope

- Full PostgreSQL catalog emulation (`pg_catalog` system tables)
- Schema creation/management commands (`CREATE SCHEMA`)
- Multi-schema routing (mapping different PostgreSQL schemas to different IRIS namespaces)

### Key Entities

- **Schema Mapping**: A translation rule that converts PostgreSQL schema names to IRIS schema names
  - Source: PostgreSQL schema name (`public`)
  - Target: IRIS schema name (`SQLUser`)
  - Direction: Bidirectional (input queries and output results)

---

## Success Criteria

1. **Prisma Introspection**: `prisma db pull` completes successfully and generates valid model definitions for all SQLUser tables.
2. **SQLAlchemy Reflection**: `metadata.reflect()` discovers all user tables when connected via PGWire.
3. **Query Compatibility**: Queries using `public.tablename` syntax execute successfully.
4. **Performance**: No measurable latency increase (< 1ms per query).
5. **Backward Compatibility**: Existing queries using `SQLUser` schema continue to work.

---

## Assumptions

1. The default IRIS namespace for user tables is `SQLUser` (standard IRIS configuration), but this may vary.
2. PostgreSQL clients default to `public` schema when no schema is specified.
3. IRIS's `information_schema` views already exist and return valid metadata.
4. The mapping handles `public` ↔ configurable IRIS schema (default: `SQLUser`).

## Configuration

The IRIS schema name is configurable via:

1. **Environment Variable**: `PGWIRE_IRIS_SCHEMA` (read at startup)
   ```bash
   export PGWIRE_IRIS_SCHEMA=MyAppSchema
   ```

2. **Programmatic API**: `configure_schema()` function for runtime changes
   ```python
   from iris_pgwire.schema_mapper import configure_schema

   # Simple: set IRIS schema
   configure_schema(iris_schema="MyAppSchema")

   # Advanced: provide custom mapping dict
   configure_schema(mapping={"public": "MyAppSchema"})
   ```

3. **Introspection**: `get_schema_config()` returns current configuration
   ```python
   from iris_pgwire.schema_mapper import get_schema_config

   config = get_schema_config()
   # {'iris_schema': 'SQLUser', 'postgres_schema': 'public', 'source': 'default'}
   ```

---

## Dependencies

- IRIS must have `information_schema` views available (confirmed in IRIS 2024.1+)
- PGWire SQL translator must support query rewriting
- Existing vector optimizer infrastructure can be extended for schema mapping

---

## Test Plan

### Unit Tests
- Schema name translation logic (public → SQLUser, SQLUser → SQLUser, %SYS → %SYS)
- Case insensitivity handling
- Query pattern matching for information_schema queries

### Integration Tests
- Query `information_schema.tables WHERE table_schema = 'public'` returns SQLUser tables
- Query `information_schema.columns` with public schema filter works
- `SELECT * FROM public.tablename` resolves correctly

### E2E Tests (ORM Compatibility)
- **Prisma**: Run `prisma db pull` and verify generated schema matches IRIS tables
- **SQLAlchemy**: Run `metadata.reflect()` and verify table discovery
- **psycopg3**: Execute information_schema queries and verify results

---

## Execution Status

- [x] User description parsed
- [x] Key concepts extracted
- [x] Ambiguities marked (none - requirements are clear)
- [x] User scenarios defined
- [x] Requirements generated
- [x] Entities identified
- [x] Review checklist passed

# Feature Specification: Prisma Catalog Support

**Feature Branch**: `031-prisma-catalog-support`
**Created**: 2025-12-23
**Status**: Draft
**Input**: User description: "implement complex information_schema features that prisma relies on"

---

## Overview

Enable Prisma ORM database introspection (`prisma db pull`) to work with IRIS PGWire by implementing the PostgreSQL system catalog tables and views that Prisma queries during schema discovery.

## Problem Statement

Prisma's `db pull` command introspects database schemas by querying PostgreSQL system catalogs (`pg_catalog` schema). These system tables provide metadata about tables, columns, constraints, indexes, and relationships. Currently, IRIS PGWire intercepts some basic catalog queries but lacks the comprehensive catalog emulation needed for Prisma to successfully generate a Prisma schema from IRIS tables.

**Current State**: Prisma introspection fails with errors related to missing catalog tables (`pg_class`, `pg_attribute`, `pg_constraint`, `pg_index`) and array parameter serialization issues.

**Desired State**: Prisma can run `prisma db pull` against IRIS PGWire and generate a complete, accurate Prisma schema reflecting IRIS table structures.

---

## User Scenarios & Testing

### Primary User Story
As a Node.js developer using Prisma ORM, I want to connect Prisma to my IRIS database via PGWire so that I can use Prisma's type-safe database client to query my existing IRIS tables without manually writing the Prisma schema.

### Acceptance Scenarios

1. **Given** a Prisma project configured to connect to IRIS PGWire, **When** running `prisma db pull`, **Then** Prisma generates a `schema.prisma` file with models matching IRIS table structures.

2. **Given** an IRIS database with tables containing primary keys, **When** Prisma introspects the schema, **Then** the generated models include correct `@id` annotations on primary key fields.

3. **Given** an IRIS database with foreign key relationships between tables, **When** Prisma introspects the schema, **Then** the generated models include correct `@relation` annotations reflecting the relationships.

4. **Given** an IRIS table with various column types (VARCHAR, INTEGER, DATE, TIMESTAMP, etc.), **When** Prisma introspects the schema, **Then** column types are correctly mapped to Prisma field types.

5. **Given** an IRIS table with unique constraints, **When** Prisma introspects the schema, **Then** the generated models include correct `@unique` annotations.

6. **Given** an IRIS table with indexes, **When** Prisma introspects the schema, **Then** the generated models include correct `@@index` annotations.

7. **Given** an IRIS table with NOT NULL constraints, **When** Prisma introspects the schema, **Then** non-nullable fields are correctly marked without the `?` optional modifier.

8. **Given** an IRIS table with default values, **When** Prisma introspects the schema, **Then** fields include appropriate `@default` annotations.

### Edge Cases

- **Empty database**: Prisma introspection succeeds but generates an empty schema
- **Tables with no primary key**: Prisma handles appropriately (may skip or warn)
- **Circular foreign key references**: Relationships are correctly represented
- **Reserved word column names**: Columns with PostgreSQL reserved names are handled
- **Very long table/column names**: Names exceeding PostgreSQL limits are handled
- **Tables in non-default schema**: Schema mapping (public → SQLUser) works correctly

---

## Requirements

### Functional Requirements

#### Core Catalog Tables

- **FR-001**: System MUST implement `pg_class` catalog returning table/view/index metadata for all IRIS tables in the mapped schema
- **FR-002**: System MUST implement `pg_attribute` catalog returning column metadata (name, type, position, nullability) for all table columns
- **FR-003**: System MUST implement `pg_constraint` catalog returning constraint metadata (primary keys, foreign keys, unique constraints, check constraints)
- **FR-004**: System MUST implement `pg_index` catalog returning index metadata for all table indexes
- **FR-005**: System MUST implement `pg_namespace` catalog returning schema metadata (already partially implemented)

#### Supporting Catalog Tables

- **FR-006**: System MUST implement `pg_type` catalog with type OID mappings for all IRIS data types (already partially implemented)
- **FR-007**: System MUST implement `pg_attrdef` catalog returning column default value expressions

#### Query Support

- **FR-009**: System MUST support array parameters in catalog queries (Prisma sends arrays of OIDs/names)
- **FR-010**: System MUST support JOIN queries across multiple catalog tables
- **FR-011**: System MUST return consistent OID values across queries (same table returns same OID)
- **FR-012**: System MUST support the `::regclass` cast for converting names to OIDs

#### Data Mapping

- **FR-013**: System MUST map IRIS `SQLUser` schema tables to PostgreSQL `public` schema in catalog results
- **FR-014**: System MUST map IRIS data types to PostgreSQL type OIDs correctly
- **FR-015**: System MUST generate stable, deterministic OIDs for IRIS objects (tables, columns, constraints)

#### Prisma-Specific Support

- **FR-016**: System MUST support the specific catalog queries Prisma sends during introspection
- **FR-017**: System MUST return foreign key relationship information in the format Prisma expects
- **FR-018**: System MUST support `information_schema` views that Prisma may also query

### Key Entities

- **pg_class**: Represents tables, views, indexes, sequences (oid, relname, relnamespace, relkind, relowner)
- **pg_attribute**: Represents columns (attrelid, attname, atttypid, attnum, attnotnull, atthasdef)
- **pg_constraint**: Represents constraints (oid, conname, contype, conrelid, confrelid, conkey, confkey)
- **pg_index**: Represents indexes (indexrelid, indrelid, indkey, indisunique, indisprimary)
- **pg_namespace**: Represents schemas (oid, nspname)
- **pg_type**: Represents data types (oid, typname, typnamespace, typlen, typtype)
- **pg_attrdef**: Represents default values (oid, adrelid, adnum, adbin)

---

## Success Criteria

1. **Prisma Introspection Success**: `prisma db pull` completes without errors against IRIS PGWire
2. **Schema Accuracy**: Generated Prisma schema correctly represents at least 95% of IRIS table structures (tables, columns, types, primary keys, foreign keys)
3. **Type Mapping Completeness**: All common IRIS data types (VARCHAR, INTEGER, BIGINT, DATE, TIMESTAMP, DECIMAL, BIT) are correctly mapped to Prisma types
4. **Relationship Discovery**: Foreign key relationships between tables are correctly identified and represented in the Prisma schema
5. **Index Recognition**: Table indexes are discovered and represented in the generated schema
6. **Constraint Accuracy**: Primary key, unique, and not-null constraints are accurately reflected
7. **Performance**: Introspection of a 50-table database completes in under 30 seconds
8. **Stability**: Repeated introspection runs produce identical schemas

---

## Assumptions

1. Prisma uses standard PostgreSQL catalog queries (not custom/proprietary queries)
2. IRIS INFORMATION_SCHEMA provides sufficient metadata to populate catalog responses
3. Stable OID generation can be achieved via deterministic hashing of object names
4. Array parameter handling can be implemented in the existing SQL translator
5. The existing schema mapping (public ↔ SQLUser) will be extended to catalog queries

## Dependencies

- Feature 030 (PostgreSQL Schema Mapping) - for schema name translation
- Existing pg_type implementation - as foundation for type catalog
- Existing pg_namespace implementation - as foundation for schema catalog

## Out of Scope

- PostgreSQL-specific features not supported by IRIS (e.g., table inheritance, partitioning, row-level security)
- Prisma Migrate functionality (`prisma migrate`) - only introspection is targeted
- Advanced PostgreSQL types (arrays, composites, ranges, domains)
- Materialized views
- Stored procedures/functions catalog
- `pg_depend` catalog (dependency tracking) - not required for Prisma introspection; used only for migration DROP CASCADE operations which are out of scope

---

## Execution Status

- [x] User description parsed
- [x] Key concepts extracted
- [x] Ambiguities marked
- [x] User scenarios defined
- [x] Requirements generated
- [x] Entities identified
- [ ] Review checklist passed

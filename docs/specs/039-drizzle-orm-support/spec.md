# Feature Specification: Drizzle ORM DDL Translation Support

**Feature Branch**: `039-drizzle-orm-support`  
**Created**: 2025-02-09  
**Status**: Draft  
**Input**: User description: "Drizzle support for sim.ai port: Drizzle migrations are SQL files that Drizzle ORM auto-generates when you change the schema in packages/db/schema.ts. They live in a migrations folder and contain standard PostgreSQL DDL statements like CREATE TABLE, ALTER TABLE, CREATE INDEX. The issue is that the SQL Drizzle generates is PostgreSQL-dialect, and IRIS SQL (even through pgwire) has compatibility gaps: 1) Reserved words, 2) Data types, 3) Index syntax, 4) ALTER TABLE variations. A better long-term approach would be to figure out exactly which Drizzle-generated SQL statements fail through pgwire and either fix them in iris-pgwire (the translation layer) so standard PostgreSQL DDL works or write a Drizzle dialect or post-processor that rewrites the SQL for IRIS compatibility."

## Clarifications

### Session 2026-02-09

- Q: When PostgreSQL types have precision/features that IRIS cannot fully support (e.g., `numeric(1000,500)`, nanosecond-precision timestamps), how should the system respond? → A: Error on unsupported precision with clear message suggesting closest supported alternative
- Q: When a migration file with multiple DDL statements fails partway through (e.g., statement 5 of 10 fails), what should happen to the `__drizzle_migrations` journal and the database state? → A: Entire migration file wrapped in single transaction - if any statement fails, rollback all changes and do not update journal (all-or-nothing)
- Q: When Drizzle generates CREATE INDEX statements with PostgreSQL-specific advanced features (INCLUDE columns, partial indexes with WHERE clauses, expression indexes) that IRIS may not support, how should the system respond? → A: Error on unsupported features with message suggesting simplified index syntax or manual IRIS-specific index creation
- Q: In distributed deployments where multiple instances might attempt to run migrations simultaneously, how should the system prevent race conditions and ensure only one migration process succeeds? → A: Database-level advisory lock on `__drizzle_migrations` table - first process acquires lock, others wait or fail immediately

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Automatic Schema Sync (Priority: P1)

Developers using Drizzle ORM can run their auto-generated migration files against IRIS through the pgwire connection without manual SQL rewriting. When schema changes are made in `packages/db/schema.ts`, the Drizzle migration files execute successfully, and the `__drizzle_migrations` journal tracks applied migrations correctly.

**Why this priority**: This is the core value proposition - eliminating manual table reconstruction scripts and keeping schema in sync automatically. Without this, the feature has no value.

**Independent Test**: Can be fully tested by generating a Drizzle migration with CREATE TABLE statements containing reserved words and PostgreSQL-specific types, then running it through iris-pgwire and verifying the tables are created correctly in IRIS.

**Acceptance Scenarios**:

1. **Given** a fresh IRIS database with pgwire enabled, **When** Drizzle runs a CREATE TABLE migration with columns named using PostgreSQL-safe but IRIS-reserved words (e.g., "level", "trigger", "key"), **Then** the table is created successfully with properly quoted identifiers
2. **Given** an existing schema, **When** Drizzle runs an ALTER TABLE migration to add columns, **Then** the columns are added without errors and data integrity is maintained
3. **Given** completed migrations, **When** querying the `__drizzle_migrations` table, **Then** all applied migrations are recorded with correct timestamps and status

---

### User Story 2 - PostgreSQL Type Mapping (Priority: P1)

Developers define tables using standard PostgreSQL types (`text`, `boolean`, `jsonb`, `timestamp with time zone`) in their Drizzle schema, and these types are correctly translated to IRIS-compatible types when CREATE TABLE or ALTER TABLE statements execute through pgwire.

**Why this priority**: Type incompatibility is a critical blocker - if data types don't work, no schema migration can succeed. This must work for P1 to deliver value.

**Independent Test**: Can be fully tested by creating a table with all common PostgreSQL types used by Drizzle (text, boolean, integer, jsonb, timestamp variants) and verifying data can be inserted, queried, and retrieved with correct type semantics in IRIS.

**Acceptance Scenarios**:

1. **Given** a CREATE TABLE statement with `text` columns, **When** executed through pgwire, **Then** columns are created with appropriate IRIS VARCHAR or CLOB types that support the same operations
2. **Given** a table with `boolean` columns, **When** data is inserted and queried, **Then** true/false values behave consistently with PostgreSQL semantics
3. **Given** a table with `jsonb` columns, **When** JSON data is stored and retrieved, **Then** data integrity and query operations work as expected
4. **Given** a table with `timestamp with time zone` columns, **When** timestamps are stored, **Then** timezone information is preserved and queries return correct timestamps

---

### User Story 3 - Index Creation Compatibility (Priority: P2)

Developers create indexes using Drizzle's index generation syntax, and CREATE INDEX statements execute successfully against IRIS through pgwire, creating functionally equivalent indexes that support query performance optimization.

**Why this priority**: Indexes are important for performance but not critical for schema synchronization. Applications can function without indexes (with degraded performance), so this can be delivered after basic table/column support.

**Independent Test**: Can be fully tested by running Drizzle-generated CREATE INDEX statements (including multi-column, partial, and expression indexes) and verifying that queries using those indexes perform as expected.

**Acceptance Scenarios**:

1. **Given** a CREATE INDEX statement with standard single-column syntax, **When** executed through pgwire, **Then** the index is created and queries use it for optimization
2. **Given** a CREATE INDEX statement with multi-column syntax, **When** executed, **Then** the composite index is created with correct column order
3. **Given** a CREATE INDEX statement with index name conflicts, **When** executed, **Then** appropriate error messages guide developers to resolution

---

### User Story 4 - Reserved Word Handling (Priority: P2)

When Drizzle-generated SQL contains unquoted identifiers that are reserved words in IRIS (but not PostgreSQL), the pgwire translation layer automatically quotes these identifiers to prevent syntax errors, without requiring developers to modify their Drizzle schema definitions.

**Why this priority**: While critical for certain column names, this is solvable with explicit quoting in the Drizzle schema as a workaround. It's important for developer experience but not a fundamental blocker if P1 stories work.

**Independent Test**: Can be fully tested by creating tables with column names matching IRIS reserved words (level, trigger, key, value, state) without quotes in the Drizzle schema, then verifying the DDL executes successfully.

**Acceptance Scenarios**:

1. **Given** a CREATE TABLE with column named "level", **When** executed through pgwire, **Then** the column is created with proper quoting and accessible via queries
2. **Given** an existing table, **When** ALTER TABLE adds a column named "trigger", **Then** the column is added with proper quoting
3. **Given** a table with reserved word columns, **When** SELECT/INSERT/UPDATE queries reference these columns, **Then** the queries execute correctly with automatic quoting

---

### Edge Cases

- **Partial Migration Failure**: Each migration file is executed within a single transaction. If any DDL statement fails, all changes from that migration are rolled back and the `__drizzle_migrations` journal is not updated. This provides all-or-nothing semantics - migrations either fully succeed or fully fail, preventing partial schema corruption.

- **Type Precision Loss**: When PostgreSQL types have precision that IRIS doesn't support (e.g., `numeric(1000,500)` exceeding IRIS max of `NUMERIC(38,19)`, or nanosecond timestamps), the system will return a clear error message indicating the unsupported precision and suggesting the closest supported IRIS type. Developers must then modify their Drizzle schema to use compatible precision limits.

- **Index Syntax Variants**: When Drizzle generates CREATE INDEX statements with PostgreSQL-specific features (INCLUDE columns, WHERE clauses for partial indexes, or expression indexes) that IRIS does not support, the system will return a clear error message identifying the unsupported feature and suggesting either simplified standard index syntax or manual creation of an IRIS-specific equivalent index.

- **Concurrent Migrations**: In distributed deployments, the system prevents race conditions by acquiring a database-level advisory lock on the `__drizzle_migrations` table before executing migrations. The first process to acquire the lock proceeds with migration execution; other processes either wait for the lock to be released or fail immediately depending on lock timeout configuration. This ensures only one migration process modifies the schema at a time.

- **Schema Name Conflicts**: What happens if Drizzle uses schema names that conflict with IRIS system schemas or reserved namespaces?

- **Large Migration Files**: How does the system handle migration files with hundreds of DDL statements or very large DEFAULT values (e.g., large JSON defaults)? Are there size limits that could cause failures?

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: System MUST translate CREATE TABLE statements from PostgreSQL DDL syntax to IRIS-compatible SQL, handling reserved word quoting automatically
- **FR-002**: System MUST map PostgreSQL data types (`text`, `boolean`, `jsonb`, `integer`, `bigint`, `timestamp`, `timestamp with time zone`, `numeric`, `serial`, `uuid`) to functionally equivalent IRIS types. When PostgreSQL types specify precision that exceeds IRIS limits (e.g., `numeric(1000,500)` when IRIS max is `NUMERIC(38,19)`), the system MUST return a clear error message indicating the unsupported precision and suggesting the closest supported IRIS type.
- **FR-003**: System MUST support ALTER TABLE ADD COLUMN statements with proper type translation and default value handling
- **FR-004**: System MUST support ALTER TABLE DROP COLUMN statements
- **FR-005**: System MUST support ALTER TABLE RENAME COLUMN statements with reserved word handling
- **FR-006**: System MUST support CREATE INDEX statements with single-column and multi-column index definitions. When CREATE INDEX contains PostgreSQL-specific features not supported by IRIS (INCLUDE columns, WHERE clauses for partial indexes, expression indexes), the system MUST return a clear error message identifying the unsupported feature and suggesting simplified standard syntax or manual IRIS-specific index creation.
- **FR-007**: System MUST support DROP INDEX statements
- **FR-008**: System MUST preserve the `__drizzle_migrations` journal table functionality, allowing Drizzle to track which migrations have been applied. In distributed deployments, the system MUST acquire an exclusive lock on the `__drizzle_migrations` table (via LOCK TABLE statement) before executing migrations to prevent race conditions. The first process to acquire the lock proceeds; others wait or fail based on timeout configuration.
- **FR-009**: System MUST handle PRIMARY KEY constraints in CREATE TABLE statements
- **FR-010**: System MUST handle NOT NULL constraints
- **FR-011**: System MUST handle DEFAULT value clauses with proper type coercion
- **FR-012**: System MUST handle UNIQUE constraints
- **FR-013**: System MUST automatically quote identifiers (table names, column names, index names) that are IRIS reserved words but valid in PostgreSQL
- **FR-014**: System MUST provide clear error messages when unsupported DDL syntax is encountered, indicating what specific construct is not supported
- **FR-015**: System MUST support DROP TABLE statements with both CASCADE and RESTRICT options, translating them to IRIS-equivalent behaviors - CASCADE automatically drops dependent objects (foreign keys, views), RESTRICT fails if dependencies exist
- **FR-016**: System MUST wrap each migration file execution in a single transaction. If any DDL statement fails, all changes from that migration MUST be rolled back and the `__drizzle_migrations` journal MUST NOT be updated, providing all-or-nothing semantics.
- **FR-017**: System MUST support common PostgreSQL DEFAULT expressions (e.g., `CURRENT_TIMESTAMP`, `gen_random_uuid()`, simple literals) by mapping them to IRIS equivalents

### Key Entities

- **Drizzle Migration File**: A SQL file containing one or more DDL statements (CREATE TABLE, ALTER TABLE, CREATE INDEX, etc.) generated by Drizzle ORM when schema changes are detected. Contains standard PostgreSQL syntax.

- **`__drizzle_migrations` Journal**: A table maintained by Drizzle to track which migration files have been successfully applied, including columns for migration ID, hash, timestamp, and execution status.

- **Reserved Word Mapping**: A catalog of words that are reserved in IRIS SQL but not in PostgreSQL, used to determine which identifiers require automatic quoting during translation.

- **Type Translation Map**: A mapping from PostgreSQL type names to IRIS-compatible type definitions, including length/precision considerations and behavioral equivalents.

- **DDL Statement**: An individual Data Definition Language command (CREATE, ALTER, DROP) that modifies database schema structure.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: Developers can run Drizzle-generated migration files containing CREATE TABLE statements without manual SQL modification, and tables are created correctly in IRIS 100% of the time for migrations using supported DDL syntax
- **SC-002**: Data inserted into tables created via Drizzle migrations can be queried and updated using standard SQL through pgwire with correct type semantics (no data corruption or type coercion errors)
- **SC-003**: The `__drizzle_migrations` journal table accurately reflects migration status after each migration run, allowing Drizzle to correctly determine which migrations have been applied
- **SC-004**: When unsupported DDL syntax is encountered, developers receive actionable error messages within 100ms that identify the specific unsupported construct and suggest alternatives or workarounds
- **SC-005**: Schema synchronization time for typical Drizzle migrations (10-50 DDL statements) completes within 5 seconds, comparable to PostgreSQL performance
- **SC-006**: Applications using Drizzle ORM against IRIS via pgwire can perform standard CRUD operations (Create, Read, Update, Delete) on migrated tables without errors or unexpected behavior
- **SC-007**: 90% of common Drizzle schema patterns (as measured by analysis of public Drizzle project repositories) execute successfully without requiring schema modifications or workarounds

## Assumptions & Dependencies

### Assumptions

- Drizzle ORM generates standard PostgreSQL DDL syntax (as of Drizzle Kit v0.x, the current stable version)
- The sim.ai project uses a standard Drizzle migration workflow with migration files stored in a `migrations/` directory
- IRIS 2024.2+ is the target platform, with all documented pgwire features available
- The existing iris-pgwire translator infrastructure can be extended to handle DDL translation (currently focused on DML/DQL)
- Developers are willing to use explicitly quoted identifiers in their Drizzle schema for reserved words as a fallback if automatic quoting has edge cases
- Transaction support in IRIS via pgwire is sufficient to roll back failed migrations

### Dependencies

- **iris-pgwire v1.3.x+**: The PostgreSQL wire protocol adapter that this feature extends
- **Drizzle ORM**: The migration file generator (external dependency, version compatibility must be tested)
- **IRIS 2024.2+**: The database with pgwire support
- **SQL Parser Infrastructure**: Existing or new parsing logic to analyze and rewrite DDL statements

### Out of Scope

- **Custom Drizzle Dialect**: Creating a fully custom Drizzle dialect plugin is out of scope; this feature focuses on translation at the pgwire layer
- **Stored Procedures/Functions**: DDL for CREATE FUNCTION or CREATE PROCEDURE is not part of typical Drizzle migrations and is out of scope
- **Complex Constraints**: CHECK constraints with complex expressions, EXCLUDE constraints, and other advanced PostgreSQL constraint types are out of scope for initial release
- **Foreign Key Cascade Behaviors**: Advanced CASCADE/SET NULL/SET DEFAULT behaviors may have limited support; basic FOREIGN KEY constraints with ON DELETE/ON UPDATE are in scope but complex cascades are deferred
- **Performance Optimization**: Index optimization and query planning differences between PostgreSQL and IRIS are out of scope; the focus is functional compatibility
- **Schema Migration Rollback**: Drizzle's ability to generate rollback migrations (migration "down" scripts) is outside the control of this feature; only forward migrations are in scope

## Notes

- **Implementation Guidance**: This spec intentionally avoids prescribing whether the solution should be implemented as DDL translation within the iris-pgwire Python layer, SQL rewriting at the protocol level, or a hybrid approach. The implementation plan will determine the optimal technical approach.

- **Testing Strategy**: Integration testing should include running the actual `drizzle-kit migrate` command against a test IRIS instance, not just unit testing individual DDL statements, to ensure end-to-end compatibility with Drizzle's migration runner.

- **Reserved Words Source**: The definitive list of IRIS reserved words should be sourced from InterSystems documentation and kept in sync with IRIS version updates.

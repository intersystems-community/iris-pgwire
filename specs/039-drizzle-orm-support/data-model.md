# Data Model: Drizzle ORM DDL Translation

## Overview

This document defines the data structures and state machines for the Drizzle ORM DDL translation feature in iris-pgwire. The model supports translating PostgreSQL DDL statements into IRIS-compatible SQL while tracking migration state and handling concurrent execution.

---

## Core Entities

### 1. DDLStatement

Represents a single parsed DDL statement from a Drizzle migration file.

**Attributes**:
- `statement_type`: str - Type of DDL operation (CREATE_TABLE, ALTER_TABLE, DROP_TABLE, CREATE_INDEX, DROP_INDEX)
- `raw_sql`: str - Original PostgreSQL SQL statement
- `translated_sql`: str | None - IRIS-compatible SQL after translation
- `schema_name`: str | None - Target schema/package name
- `table_name`: str | None - Target table name
- `index_name`: str | None - Target index name (for index operations)
- `columns`: List[ColumnDefinition] - Column definitions (for CREATE/ALTER TABLE)
- `constraints`: List[ConstraintDefinition] - Table constraints
- `translation_warnings`: List[str] - Warnings generated during translation
- `is_translatable`: bool - Whether statement can be translated to IRIS
- `skip_reason`: str | None - Reason if statement must be skipped

**Validation Rules**:
- `statement_type` must be one of the supported DDL types
- `table_name` required for TABLE operations
- `index_name` required for INDEX operations
- If `is_translatable` is False, `skip_reason` must be provided
- `translated_sql` must be present if `is_translatable` is True

**State Transitions**: N/A (immutable after parsing)

---

### 2. ColumnDefinition

Represents a column in a CREATE TABLE or ALTER TABLE statement.

**Attributes**:
- `name`: str - Column name (may be quoted)
- `pg_type`: str - Original PostgreSQL data type
- `iris_type`: str - Mapped IRIS data type
- `precision`: int | None - Numeric precision (for NUMERIC, DECIMAL types)
- `scale`: int | None - Numeric scale
- `max_length`: int | None - String max length (for VARCHAR, TEXT)
- `is_nullable`: bool - Whether column allows NULL
- `default_value`: str | None - Default value expression
- `is_primary_key`: bool - Whether column is part of primary key
- `is_unique`: bool - Whether column has UNIQUE constraint
- `references`: ForeignKeyReference | None - Foreign key relationship

**Validation Rules**:
- `name` must not be empty
- `pg_type` must be a recognized PostgreSQL type
- `iris_type` must be a valid IRIS type from type_mapping registry
- If `precision` > 38, validation must error (IRIS NUMERIC limit)
- `precision` and `scale` only valid for numeric types
- `max_length` only valid for character types

**Type Mapping Examples**:
```
text → VARCHAR(*)
boolean → BIT
uuid → UUID  
jsonb → JSON
timestamp with time zone → TIMESTAMP
serial → INTEGER (with AUTO_INCREMENT)
bigserial → BIGINT (with AUTO_INCREMENT)
numeric(p,s) → NUMERIC(p,s) [if p ≤ 38]
```

---

### 3. ConstraintDefinition

Represents a table constraint (PRIMARY KEY, FOREIGN KEY, UNIQUE, CHECK).

**Attributes**:
- `constraint_type`: str - Type of constraint (PRIMARY_KEY, FOREIGN_KEY, UNIQUE, CHECK)
- `name`: str | None - Constraint name (may be auto-generated)
- `columns`: List[str] - Column names involved in constraint
- `referenced_table`: str | None - Referenced table (for FOREIGN KEY)
- `referenced_columns`: List[str] | None - Referenced columns (for FOREIGN KEY)
- `on_delete`: str | None - ON DELETE action (CASCADE, RESTRICT, SET NULL, SET DEFAULT)
- `on_update`: str | None - ON UPDATE action
- `check_expression`: str | None - CHECK constraint expression

**Validation Rules**:
- `constraint_type` must be one of the supported types
- `columns` must not be empty
- For FOREIGN_KEY: `referenced_table` and `referenced_columns` required
- For CHECK: `check_expression` required
- `on_delete` and `on_update` only valid for FOREIGN_KEY

**Translation Notes**:
- CASCADE/RESTRICT behavior clarified in spec (support both with IRIS equivalents)
- Check expressions must be translated to IRIS SQL dialect

---

### 4. IndexDefinition

Represents a CREATE INDEX statement.

**Attributes**:
- `name`: str - Index name
- `table_name`: str - Target table
- `columns`: List[IndexColumn] - Indexed columns
- `is_unique`: bool - Whether index enforces uniqueness
- `index_type`: str | None - Index type (btree, hash, gin, gist - PostgreSQL-specific)
- `where_clause`: str | None - Partial index condition (PostgreSQL feature)
- `include_columns`: List[str] | None - INCLUDE columns (PostgreSQL feature)
- `is_concurrent`: bool - Whether index creation is CONCURRENT

**Validation Rules**:
- `name` and `table_name` required
- `columns` must not be empty
- If `index_type` not in IRIS-supported types, must error with guidance
- If `where_clause` or `include_columns` present, must error (unsupported advanced features)
- `is_concurrent` must be False (IRIS doesn't support CONCURRENTLY)

**IndexColumn Sub-Entity**:
- `name`: str - Column name
- `direction`: str | None - Sort order (ASC, DESC)
- `nulls_order`: str | None - NULLS FIRST/LAST (PostgreSQL feature)

**Translation Strategy**:
- Strip unsupported PostgreSQL-specific features (USING btree, WHERE clause, INCLUDE)
- Error if advanced features cannot be safely ignored
- Basic multi-column indexes translate directly

---

### 5. MigrationFile

Represents a single Drizzle migration file.

**Attributes**:
- `filename`: str - Migration file name (e.g., "0001_init.sql")
- `file_path`: str - Absolute path to migration file
- `content`: str - Raw SQL content
- `statements`: List[DDLStatement] - Parsed DDL statements
- `execution_order`: int - Order in migration sequence
- `checksum`: str - Content hash for integrity checking
- `applied_at`: datetime | None - Timestamp when migration was applied
- `execution_time_ms`: int | None - Execution duration in milliseconds
- `status`: MigrationStatus - Current status

**MigrationStatus Enum**:
- `PENDING` - Not yet applied
- `IN_PROGRESS` - Currently executing
- `COMPLETED` - Successfully applied
- `FAILED` - Execution failed
- `ROLLED_BACK` - Rolled back due to error

**State Transitions**:
```
PENDING → IN_PROGRESS → COMPLETED
           ↓
        FAILED → ROLLED_BACK (if transaction rollback succeeds)
```

**Validation Rules**:
- `filename` must match Drizzle naming pattern
- `execution_order` must be unique and sequential
- `statements` must not be empty
- `checksum` must match file content
- If `status` is COMPLETED, `applied_at` and `execution_time_ms` required

---

### 6. MigrationJournal

Represents the `__drizzle_migrations` table state.

**Attributes**:
- `id`: int - Auto-increment primary key
- `hash`: str - Migration file hash
- `created_at`: datetime - Timestamp when migration was applied

**Table Schema** (IRIS-compatible):
```sql
CREATE TABLE "__drizzle_migrations" (
    "id" INTEGER PRIMARY KEY AUTO INCREMENT,
    "hash" VARCHAR(255) NOT NULL UNIQUE,
    "created_at" TIMESTAMP DEFAULT CURRENT_TIMESTAMP
)
```

**Validation Rules**:
- `hash` must be unique (prevents duplicate migration application)
- `created_at` auto-populated if not provided

**Interaction Pattern**:
1. Query journal for existing hashes before applying migrations
2. Insert new entry only after migration COMMIT succeeds
3. Never insert if migration ROLLBACK occurs

---

### 7. ReservedWordMapping

Represents IRIS reserved words that require quoting.

**Attributes**:
- `word`: str - Reserved word (uppercase)
- `category`: str - Category (keyword, function_name, data_type)
- `requires_quoting`: bool - Whether word must be quoted in IRIS

**Data Source**: Loaded from IRIS reserved words documentation

**Usage**:
- Check all unquoted identifiers (table names, column names, index names) against this mapping
- Automatically quote identifiers that match IRIS reserved words
- Preserve original casing when quoting

---

### 8. TypeMappingEntry

Represents PostgreSQL → IRIS type translation rules.

**Attributes**:
- `pg_type`: str - PostgreSQL type name
- `iris_type`: str - IRIS type name
- `max_precision`: int | None - Maximum precision for numeric types
- `max_scale`: int | None - Maximum scale for numeric types
- `requires_length`: bool - Whether type requires explicit length parameter
- `default_length`: int | None - Default length if not specified

**Examples**:
```python
TypeMappingEntry(pg_type="text", iris_type="VARCHAR", requires_length=False)
TypeMappingEntry(pg_type="boolean", iris_type="BIT", requires_length=False)
TypeMappingEntry(pg_type="uuid", iris_type="UUID", requires_length=False)
TypeMappingEntry(pg_type="numeric", iris_type="NUMERIC", max_precision=38, max_scale=19, requires_length=True)
TypeMappingEntry(pg_type="jsonb", iris_type="JSON", requires_length=False)
TypeMappingEntry(pg_type="timestamp with time zone", iris_type="TIMESTAMP", requires_length=False)
```

**Data Source**: Extends existing `iris_pgwire.type_mapping` registry

---

### 9. TranslationContext

Holds runtime state during DDL translation.

**Attributes**:
- `migration_file`: MigrationFile - Current migration being processed
- `connection`: IRISConnection - Active database connection
- `transaction_active`: bool - Whether transaction is open
- `lock_acquired`: bool - Whether migration lock is held
- `warnings`: List[str] - Accumulated warnings
- `errors`: List[str] - Accumulated errors
- `strict_mode`: bool - Whether to fail on unsupported features vs skip with warning

**Lifecycle**:
1. Created when migration execution starts
2. Transaction opened and lock acquired
3. Statements translated and executed sequentially
4. On success: commit transaction, release lock, update journal
5. On failure: rollback transaction, release lock, DO NOT update journal

---

### 10. DDLTranslationError

Exception raised when DDL translation fails.

**Attributes**:
- `statement`: DDLStatement - The statement that failed
- `error_code`: str - Error classification (TYPE_PRECISION_EXCEEDED, UNSUPPORTED_INDEX_FEATURE, RESERVED_WORD_CONFLICT, etc.)
- `message`: str - Human-readable error message with guidance
- `suggested_fix`: str | None - Recommended corrective action

**Error Codes**:
- `TYPE_PRECISION_EXCEEDED` - Numeric precision > 38
- `UNSUPPORTED_INDEX_FEATURE` - Advanced PostgreSQL index features (WHERE, INCLUDE, expression indexes)
- `RESERVED_WORD_CONFLICT` - Unquoted identifier matches IRIS reserved word
- `UNSUPPORTED_CONSTRAINT` - Constraint type not supported in IRIS
- `UNSUPPORTED_DDL_OPERATION` - DDL operation not translatable

---

## Relationships

### Entity Relationship Diagram

```
MigrationFile 1──* DDLStatement
DDLStatement 1──* ColumnDefinition
DDLStatement 1──* ConstraintDefinition
ColumnDefinition 0..1── ForeignKeyReference
MigrationFile 1── MigrationJournal (via hash)
TranslationContext 1── MigrationFile
DDLStatement ── TypeMappingEntry (via pg_type lookup)
DDLStatement ── ReservedWordMapping (via identifier validation)
```

### Key Invariants

1. **Migration Atomicity**: All DDLStatements in a MigrationFile execute within a single transaction
2. **Journal Consistency**: MigrationJournal entry created only after successful COMMIT
3. **Type Safety**: Every ColumnDefinition.pg_type must have corresponding TypeMappingEntry
4. **Identifier Safety**: All unquoted identifiers checked against ReservedWordMapping
5. **Concurrency Safety**: Only one TranslationContext can hold migration lock at a time

---

## Concurrency & State Management

### Migration Lock Protocol

**Lock Acquisition**:
```sql
-- Acquire exclusive lock on journal table
LOCK TABLE "__drizzle_migrations" IN EXCLUSIVE MODE;
```

**Lock Release**:
- Automatic on COMMIT or ROLLBACK
- Ensures only one migration process executes at a time

### Transaction Semantics

**All-or-Nothing Execution**:
```
START TRANSACTION
  -- Execute all DDL statements in migration file
  -- On any failure: ROLLBACK (journal NOT updated)
  -- On success: COMMIT (then insert journal entry)
COMMIT/ROLLBACK
```

**Failure Handling**:
- Any DDLStatement failure triggers immediate ROLLBACK
- Database state reverts to pre-migration state
- Journal table remains unchanged (no partial application)

---

## Type Translation Rules

### Precision Loss Detection

**Rule**: When PostgreSQL type has precision/features that IRIS cannot support, MUST error with clear message.

**Examples**:

1. **Oversized NUMERIC**:
   ```
   Input:  NUMERIC(1000, 500)
   Output: DDLTranslationError(
             error_code="TYPE_PRECISION_EXCEEDED",
             message="NUMERIC precision 1000 exceeds IRIS limit of 38 digits",
             suggested_fix="Use NUMERIC(38, 19) or consider alternative data type"
           )
   ```

2. **Unsupported Timestamp Precision**:
   ```
   Input:  TIMESTAMP(9) -- nanosecond precision
   Output: Warning if session TimePrecision < 9, translate to TIMESTAMP with current TimePrecision
   ```

3. **PostgreSQL-specific Types**:
   ```
   Input:  citext, inet, macaddr
   Output: DDLTranslationError(
             error_code="UNSUPPORTED_TYPE",
             message="PostgreSQL type 'citext' has no IRIS equivalent",
             suggested_fix="Use VARCHAR with case-insensitive collation or application-level handling"
           )
   ```

---

## Index Translation Rules

### Supported Index Features

✅ **Fully Supported**:
- Single-column indexes
- Multi-column indexes
- UNIQUE indexes
- ASC/DESC column ordering (basic)

❌ **Unsupported (Must Error)**:
- Partial indexes (`WHERE` clause)
- INCLUDE columns
- Expression indexes (`CREATE INDEX ON table (LOWER(column))`)
- PostgreSQL-specific index types (GIN, GIST, BRIN)
- CONCURRENTLY keyword

### Translation Strategy

**Basic Index**:
```sql
-- PostgreSQL (Drizzle output)
CREATE INDEX "user_email_idx" ON "users" ("email");

-- IRIS (translated)
CREATE INDEX "user_email_idx" ON "users" ("email");
```

**Unique Multi-Column Index**:
```sql
-- PostgreSQL
CREATE UNIQUE INDEX "user_org_idx" ON "users" ("organization_id", "email");

-- IRIS (translated)
CREATE UNIQUE INDEX "user_org_idx" ON "users" ("organization_id", "email");
```

**Unsupported Features (Error)**:
```sql
-- PostgreSQL
CREATE INDEX "active_users_idx" ON "users" ("email") WHERE "active" = true;

-- Error: DDLTranslationError(
--   error_code="UNSUPPORTED_INDEX_FEATURE",
--   message="Partial indexes with WHERE clause not supported in IRIS",
--   suggested_fix="Create full index or filter in application queries"
-- )
```

---

## Reserved Word Handling

### Automatic Quoting Strategy

**Rule**: Unquoted identifiers that match IRIS reserved words MUST be automatically quoted to preserve PostgreSQL semantics.

**Examples**:

1. **Reserved Column Name**:
   ```sql
   -- Drizzle input
   CREATE TABLE "workflow" (
     "id" text PRIMARY KEY,
     "level" integer NOT NULL  -- "level" is IRIS reserved
   );
   
   -- IRIS translation (automatic quoting applied)
   CREATE TABLE "workflow" (
     "id" VARCHAR(*) PRIMARY KEY,
     "level" INTEGER NOT NULL  -- Quoted preserved
   );
   ```

2. **Reserved Table Name**:
   ```sql
   -- Drizzle input
   CREATE TABLE trigger (id text);  -- "trigger" is IRIS reserved
   
   -- IRIS translation
   CREATE TABLE "trigger" (id VARCHAR(*));  -- Auto-quoted
   ```

### Reserved Words Requiring Special Handling

Based on IRIS documentation, these common Drizzle column names require quoting:
- `level`
- `key`
- `trigger`
- `option`
- `position`
- `interval`
- `zone`

**Implementation**: Load full reserved words list from IRIS docs at translator initialization.

---

## Schema Design Patterns

### Migration Journal Schema

**IRIS-Compatible Definition**:
```sql
CREATE TABLE "__drizzle_migrations" (
    "id" INTEGER PRIMARY KEY AUTO INCREMENT,
    "hash" VARCHAR(255) NOT NULL UNIQUE,
    "created_at" TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

**Key Decisions**:
- Use INTEGER for `id` (not SERIAL, which is PostgreSQL-specific)
- Use TIMESTAMP without timezone (IRIS standard)
- Preserve exact table/column names from Drizzle (quoted for case sensitivity)

### Drizzle Schema Pattern Support

**Typical Drizzle Migration**:
```sql
CREATE TABLE "users" (
  "id" uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  "email" text NOT NULL UNIQUE,
  "created_at" timestamp with time zone DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX "user_email_idx" ON "users" ("email");
```

**IRIS Translation**:
```sql
CREATE TABLE "users" (
  "id" UUID PRIMARY KEY DEFAULT gen_random_uuid(),  -- UUID function supported in IRIS
  "email" VARCHAR(*) NOT NULL UNIQUE,
  "created_at" TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX "user_email_idx" ON "users" ("email");
```

---

## Validation Summary

### Pre-Translation Validation

1. **File Integrity**: Verify migration file checksum matches content
2. **Ordering**: Ensure migration execution_order is sequential
3. **Journal Check**: Confirm migration not already applied (hash lookup)
4. **Lock Availability**: Verify no other migration in progress

### During Translation Validation

1. **Type Mapping**: Every pg_type resolves to valid iris_type
2. **Precision Limits**: Numeric types within IRIS bounds (≤38 digits)
3. **Reserved Words**: All identifiers checked and quoted if needed
4. **Feature Support**: Index/constraint features validated against IRIS capabilities

### Post-Translation Validation

1. **SQL Syntax**: Translated SQL parses correctly in IRIS
2. **Transaction State**: Verify COMMIT or ROLLBACK completed
3. **Journal Update**: Confirm migration logged if successful
4. **Lock Release**: Ensure migration lock released

---

## Error Handling & Recovery

### Recoverable Errors

**Scenarios**:
- Type precision exceeds limit → Error with suggested fix (user adjusts schema)
- Unsupported index feature → Error with guidance (user simplifies or removes index)
- Reserved word conflict → Auto-quote (transparent to user)

**Response**: Fail migration with actionable error message, DO NOT update journal, rollback transaction.

### Unrecoverable Errors

**Scenarios**:
- Database connection lost mid-transaction
- IRIS internal error during DDL execution
- Lock acquisition timeout

**Response**: ROLLBACK transaction (automatic), release lock (automatic), log error, propagate to caller.

### Concurrent Execution Conflicts

**Scenario**: Two processes attempt migration simultaneously.

**Handling**:
1. First process acquires `LOCK TABLE "__drizzle_migrations" IN EXCLUSIVE MODE`
2. Second process waits for lock (or times out)
3. First process completes → releases lock
4. Second process acquires lock, detects migration already applied (journal check), skips execution

---

## Future Extensions

### Potential Enhancements (Out of Scope for v1)

1. **Migration Rollback Support**: Generate reverse migrations for rollback capability
2. **Partial Index Emulation**: Translate WHERE clauses to triggers or materialized views
3. **Expression Index Emulation**: Create computed columns for expression indexes
4. **Advanced Type Support**: Handle PostgreSQL enums, arrays, composite types
5. **Schema Versioning**: Track schema evolution beyond migration hashes

---

## References

- [IRIS SQL DDL Commands](https://docs.intersystems.com/irislatest/csp/docbook/DocBook.UI.Page.cls?KEY=RSQL_COMMANDS)
- [IRIS Reserved Words](https://docs.intersystems.com/irislatest/csp/docbook/DocBook.UI.Page.cls?KEY=RSQL_reservedwords)
- [IRIS Type System](https://docs.intersystems.com/irislatest/csp/docbook/DocBook.UI.Page.cls?KEY=RSQL_datatypes)
- [Drizzle Migrations Fundamentals](https://orm.drizzle.team/docs/migrations)
- [iris-pgwire Type Mapping Registry](src/iris_pgwire/type_mapping.py)

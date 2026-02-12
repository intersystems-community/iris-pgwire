# PostgreSQL DDL Compatibility for InterSystems IRIS

This document describes the automatic DDL transformations and skips applied by `iris-pgwire` to ensure compatibility with PostgreSQL migration scripts.

## Overview

InterSystems IRIS does not support all PostgreSQL-specific DDL syntax. To enable seamless migrations, `iris-pgwire` automatically intercepts, transforms, or skips unsupported constructs.

## Strict Mode (`strict_ddl`)

You can control the behavior of the DDL processor via the `strict_ddl` configuration flag.

- **`strict_ddl = false` (Default)**: Unsupported constructs are automatically transformed or skipped. A warning is logged using the format `[DDL-SKIP] <construct> ignored`.
- **`strict_ddl = true`**: Unsupported constructs raise an exception, halting the migration.

## Supported Compatibility Rules

### 1. Storage Parameters (`fillfactor`)
PostgreSQL `WITH (fillfactor = ...)` or `SET (fillfactor = ...)` clauses are automatically stripped or skipped.
- **Warning**: `[DDL-SKIP] WITH (fillfactor) ignored` or `[DDL-SKIP] SET (fillfactor) ignored`.

### 2. Index Methods (`USING btree`)
The `USING btree` clause in `CREATE INDEX` statements is automatically stripped, as IRIS uses its own default indexing method.
- **Warning**: `[DDL-SKIP] USING btree ignored`.

### 3. Generated Columns (`GENERATED ALWAYS AS ... STORED`)
IRIS does not support the PostgreSQL syntax for stored generated columns. These columns are automatically **stripped** from the `CREATE TABLE` statement to allow the table creation to proceed.
- **Warning**: `[DDL-SKIP] GENERATED column ignored`.

### 4. PostgreSQL Type Casts (`::type`)
PostgreSQL-style cast syntax (e.g., `'value'::text`) in `DEFAULT` expressions or literals is automatically stripped.
- **Warning**: `[DDL-SKIP] Cast syntax ignored`.

### 5. Enum Types (`CREATE TYPE ... AS ENUM`)
PostgreSQL enum definitions are intercepted:
1. The `CREATE TYPE ... AS ENUM` statement is **skipped**.
2. The enum type name is **registered** in the session.
3. Subsequent columns using the registered enum type are automatically mapped to `VARCHAR(64)`.
- **Note**: Enum values are not validated by IRIS during the migration phase.

### 6. CHECK Constraints
`ALTER TABLE ... ADD CONSTRAINT ... CHECK` statements are automatically **skipped**.
- **Warning**: `[DDL-SKIP] CHECK constraint ignored`.

### 7. Index Skipping for Failed Tables
If a `CREATE TABLE` statement is skipped or failed, any subsequent `CREATE INDEX` statement referencing that table will also be automatically skipped.
- **Warning**: `[DDL-SKIP] Index on skipped table ignored`.

### 8. UUID and JSON Native Types
IRIS requires native class types for UUID and JSON columns in DDL:
- **UUID**: Automatically translated to `%Library.UniqueIdentifier` in both CREATE TABLE and ALTER TABLE
- **JSON/JSONB**: Automatically translated to `%Library.DynamicObject` in both CREATE TABLE and ALTER TABLE
- **DEFAULT gen_random_uuid()**: Automatically **skipped** (IRIS doesn't support function calls in DEFAULT clauses)
- **DEFAULT NOW()**: Automatically translated to `CURRENT_TIMESTAMP` (IRIS requirement)

Example transformation:
```sql
-- Input (PostgreSQL)
CREATE TABLE users (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    data jsonb NOT NULL,
    created_at timestamp DEFAULT now()
)

-- Output (IRIS)
CREATE TABLE users (
    id %Library.UniqueIdentifier PRIMARY KEY NOT NULL,
    data %Library.DynamicObject NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
)
```

### 9. ALTER TABLE RENAME COLUMN
IRIS does not support `ALTER TABLE ... RENAME COLUMN`. These statements are automatically **skipped**.
- **Warning**: `IRIS does not support ALTER TABLE RENAME COLUMN`.

### 10. Identifier Case Sensitivity
InterSystems IRIS is case-sensitive for package (schema) names and class (table) names. `iris-pgwire` ensures compatibility by:
- Always using `SQLUser` (exact case) for the target schema.
- Preserving the exact casing and quoting of identifiers (e.g., `public."workflow"` is correctly translated to `SQLUser."workflow"`).
- Ensuring that tables created with quoted lowercase names can be correctly queried by ORMs using the same quotes.

The DDL processor is part of the `SQLTranslator` pipeline and operates in two phases:
1. **Pre-normalization**: Stripping complex constructs like `GENERATED ALWAYS AS`.
2. **Post-normalization**: Stripping keywords like `USING btree` after identifier normalization.
3. **Filtering**: Skipping whole statements like `CREATE TYPE` or `SET (fillfactor)`.

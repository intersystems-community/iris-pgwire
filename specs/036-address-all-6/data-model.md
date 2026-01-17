# Data Model for DDL Compatibility Feature

## Overview
The feature introduces a few internal helper objects that the driver uses to track unsupported PostgreSQL DDL constructs and to map PostgreSQL enum types to IRIS column types.

| Entity | Description |
|--------|-------------|
| **EnumTypeRegistry** | Keeps a registry of PostgreSQL `CREATE TYPE … AS ENUM` definitions that are encountered. When an enum column is defined, the driver records the enum name and maps it to a `VARCHAR(64)` column in IRIS. The registry is used to validate later references to the enum type.
| **SkippedTableSet** | Stores the names of tables whose `CREATE TABLE` statement was skipped (e.g., because it contained unsupported generated columns). Any subsequent `CREATE INDEX` that references a table in this set is automatically skipped with a warning.
| **DDLProcessor** | Core component that parses incoming DDL statements, applies the functional‑requirements rules (skip fillfactor, generated columns, `USING btree`, cast syntax, enum registration, check constraints, index skipping) and logs warnings using the configured `strict_ddl` flag.

## Relationships
- `DDLProcessor` holds a reference to `EnumTypeRegistry` and `SkippedTableSet`.
- `EnumTypeRegistry` may be consulted by other components that need to resolve enum values at runtime.

## Persistence
The entities are in‑memory structures; there is no persistent storage required because they are only needed during a migration run.

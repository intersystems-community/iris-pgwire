# Data Model: PostgreSQL Schema Mapping

**Feature**: 030-pg-schema-mapping
**Type**: Pure translation layer (no persistent data)

## Overview

This feature does not introduce new data entities. Schema mapping is a stateless translation applied at runtime.

## Conceptual Model

```
┌─────────────────┐     ┌──────────────────┐     ┌─────────────────┐
│  PostgreSQL     │     │  Schema Mapper   │     │  IRIS           │
│  Client Query   │────▶│  (Translation)   │────▶│  SQL Execution  │
│  schema=public  │     │  public→SQLUser  │     │  schema=SQLUser │
└─────────────────┘     └──────────────────┘     └─────────────────┘
                               │
                               ▼
                        ┌──────────────────┐
                        │  Result Set      │
                        │  SQLUser→public  │
                        └──────────────────┘
```

## Translation Rules

| Direction | Input | Output | Scope |
|-----------|-------|--------|-------|
| Input (queries) | `public` | `SQLUser` | WHERE clauses, schema-qualified names |
| Output (results) | `SQLUser` | `public` | `table_schema` columns only |

## No Database Schema Changes

- No new tables
- No new columns
- No migrations required
- No configuration storage

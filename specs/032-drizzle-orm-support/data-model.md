# Data Model: Drizzle ORM Support

**Feature**: 032-drizzle-orm-support
**Date**: 2025-12-25

## Overview

This feature is primarily a **verification feature** - it validates that existing IRIS PGWire capabilities work with Drizzle ORM. The data model describes the TypeScript entities that Drizzle generates and how they map to IRIS tables.

## Drizzle Schema Entities

### DrizzleTable

Generated TypeScript table definition using `pgTable()`.

```typescript
// Example generated schema
import { pgTable, serial, text, integer, timestamp } from 'drizzle-orm/pg-core';

export const users = pgTable('users', {
  id: serial('id').primaryKey(),
  name: text('name').notNull(),
  email: text('email').unique(),
  createdAt: timestamp('created_at').defaultNow(),
});
```

**IRIS Mapping:**
- Table name: `SQLUser.users` (schema mapping translates `public` → `SQLUser`)
- Primary key: Detected from `pg_constraint` (contype='p')
- Columns: Detected from `pg_attribute`
- Unique constraints: Detected from `pg_constraint` (contype='u')

### DrizzleColumn

Column definition with type and constraints.

| Drizzle Type | PostgreSQL OID | IRIS Type |
|--------------|----------------|-----------|
| `serial()` | int4 (23) | INTEGER IDENTITY |
| `integer()` | int4 (23) | INTEGER |
| `bigint()` | int8 (20) | BIGINT |
| `text()` | text (25) | VARCHAR(MAX) |
| `varchar()` | varchar (1043) | VARCHAR(n) |
| `timestamp()` | timestamp (1114) | TIMESTAMP |
| `boolean()` | bool (16) | BIT |
| `numeric()` | numeric (1700) | DECIMAL |

### DrizzleRelation

Foreign key relationship definition.

```typescript
// Example relation
export const posts = pgTable('posts', {
  id: serial('id').primaryKey(),
  authorId: integer('author_id').references(() => users.id),
  title: text('title'),
});
```

**Detection:**
- Foreign keys from `pg_constraint` (contype='f')
- Referenced table from `confrelid`
- Referenced columns from `confkey`

### DrizzleIndex

Index definition for query optimization.

```typescript
// Example index
export const usersEmailIdx = index('users_email_idx').on(users.email);
```

**Detection:**
- Indexes from `pg_index`
- Index columns from `indkey`
- Uniqueness from `indisunique`

## Catalog Query Mapping

### Tables Discovery

**Drizzle Query** (expected):
```sql
SELECT c.relname, n.nspname, c.oid
FROM pg_class c
JOIN pg_namespace n ON n.oid = c.relnamespace
WHERE n.nspname = 'public' AND c.relkind IN ('r', 'v')
```

**IRIS PGWire Response:**
- Translates `public` to `SQLUser` internally
- Returns table metadata from INFORMATION_SCHEMA.TABLES
- Generates stable OIDs for each table

### Columns Discovery

**Drizzle Query** (expected):
```sql
SELECT a.attname, a.atttypid, a.attnotnull, a.attnum
FROM pg_attribute a
WHERE a.attrelid = $1 AND a.attnum > 0
ORDER BY a.attnum
```

**IRIS PGWire Response:**
- Returns column metadata from INFORMATION_SCHEMA.COLUMNS
- Maps IRIS types to PostgreSQL type OIDs
- Includes nullability and position

### Constraints Discovery

**Drizzle Query** (expected):
```sql
SELECT c.conname, c.contype, c.conrelid, c.confrelid, c.conkey, c.confkey
FROM pg_constraint c
WHERE c.conrelid = $1
```

**IRIS PGWire Response:**
- Primary keys (contype='p') from PRIMARY KEY constraints
- Foreign keys (contype='f') from FOREIGN KEY constraints
- Unique constraints (contype='u') from UNIQUE constraints

## State Transitions

### Drizzle-kit Introspect Flow

```
1. Connect to database (postgres.js driver)
   ↓
2. Query pg_namespace for schemas
   ↓
3. Query pg_class for tables/views
   ↓
4. For each table:
   - Query pg_attribute for columns
   - Query pg_constraint for constraints
   - Query pg_index for indexes
   ↓
5. Generate schema.ts with TypeScript definitions
```

### CRUD Operation Flow

```
1. Drizzle generates SQL query
   ↓
2. postgres.js sends via wire protocol
   ↓
3. IRIS PGWire receives and translates
   - Parameter placeholders: $1 → ?
   - Schema names: public → SQLUser
   - RETURNING clause: Emulated via LAST_IDENTITY() or post-SELECT
   ↓
4. IRIS executes translated SQL
   ↓
5. IRIS PGWire returns results
   - Schema names: SQLUser → public
   - Type OIDs mapped correctly
```

## Validation Rules

### Type Compatibility

All Drizzle column types must map to valid IRIS types:
- ✅ Numeric types (int, bigint, decimal)
- ✅ String types (text, varchar)
- ✅ Date/time types (timestamp, date)
- ✅ Boolean type (maps to BIT)
- ⚠️ Array types: NOT SUPPORTED
- ⚠️ JSON types: Limited support

### Constraint Compatibility

| Constraint | Drizzle | IRIS Support |
|------------|---------|--------------|
| PRIMARY KEY | ✅ | ✅ |
| FOREIGN KEY | ✅ | ✅ |
| UNIQUE | ✅ | ✅ |
| NOT NULL | ✅ | ✅ |
| DEFAULT | ✅ | ✅ |
| CHECK | ✅ | ✅ |

## Testing Data Model

### Sample Test Table

```sql
-- IRIS SQL
CREATE TABLE SQLUser.DrizzleTest (
    id INT IDENTITY PRIMARY KEY,
    name VARCHAR(255) NOT NULL,
    email VARCHAR(255) UNIQUE,
    age INT,
    active BIT DEFAULT 1,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

### Expected Drizzle Schema

```typescript
// Generated by drizzle-kit introspect
export const drizzleTest = pgTable('drizzle_test', {
  id: serial('id').primaryKey(),
  name: varchar('name', { length: 255 }).notNull(),
  email: varchar('email', { length: 255 }).unique(),
  age: integer('age'),
  active: boolean('active').default(true),
  createdAt: timestamp('created_at').defaultNow(),
});
```

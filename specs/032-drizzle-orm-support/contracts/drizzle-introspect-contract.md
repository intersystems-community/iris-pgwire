# Contract: Drizzle-kit Introspection

**Feature**: 032-drizzle-orm-support
**Date**: 2025-12-25

## Overview

This contract defines the expected behavior when `drizzle-kit introspect` queries IRIS PGWire for schema discovery. The introspection should successfully generate a `schema.ts` file that accurately represents IRIS table structures.

---

## TC-1: Namespace Discovery

### Query (expected)
```sql
SELECT nspname, oid
FROM pg_namespace
WHERE nspname NOT IN ('pg_catalog', 'information_schema', 'pg_toast')
```

### Expected Response

| nspname | oid |
|---------|-----|
| public | 2200 |

### Notes
- IRIS PGWire maps `SQLUser` to `public` in output
- OID 2200 is the well-known PostgreSQL OID for `public` schema

---

## TC-2: Tables Discovery

### Query (expected)
```sql
SELECT c.relname, n.nspname, c.oid, c.relkind
FROM pg_class c
JOIN pg_namespace n ON n.oid = c.relnamespace
WHERE n.nspname = 'public'
  AND c.relkind IN ('r', 'v')
ORDER BY c.relname
```

### Expected Response (example)

| relname | nspname | oid | relkind |
|---------|---------|-----|---------|
| users | public | 16384 | r |
| posts | public | 16385 | r |
| user_profiles | public | 16386 | v |

### Notes
- `relkind = 'r'` for regular tables
- `relkind = 'v'` for views
- OIDs are deterministically generated from table identity

---

## TC-3: Columns Discovery

### Query (expected)
```sql
SELECT
  a.attname,
  a.atttypid,
  a.attnotnull,
  a.attnum,
  a.atthasdef,
  t.typname
FROM pg_attribute a
JOIN pg_type t ON t.oid = a.atttypid
WHERE a.attrelid = $1
  AND a.attnum > 0
  AND NOT a.attisdropped
ORDER BY a.attnum
```

### Expected Response (for users table)

| attname | atttypid | attnotnull | attnum | atthasdef | typname |
|---------|----------|------------|--------|-----------|---------|
| id | 23 | t | 1 | t | int4 |
| name | 1043 | t | 2 | f | varchar |
| email | 1043 | f | 3 | f | varchar |
| created_at | 1114 | f | 4 | t | timestamp |

### Type OID Reference

| IRIS Type | PostgreSQL typname | OID |
|-----------|-------------------|-----|
| INTEGER | int4 | 23 |
| BIGINT | int8 | 20 |
| VARCHAR(n) | varchar | 1043 |
| VARCHAR(MAX) | text | 25 |
| TIMESTAMP | timestamp | 1114 |
| DATE | date | 1082 |
| BIT | bool | 16 |
| DECIMAL | numeric | 1700 |

---

## TC-4: Primary Key Discovery

### Query (expected)
```sql
SELECT
  c.conname,
  c.contype,
  c.conkey
FROM pg_constraint c
WHERE c.conrelid = $1
  AND c.contype = 'p'
```

### Expected Response

| conname | contype | conkey |
|---------|---------|--------|
| users_pkey | p | {1} |

### Notes
- `conkey` is an array of column numbers (attnum values)
- Single-column PK: `{1}` means column 1
- Composite PK: `{1,2}` means columns 1 and 2

---

## TC-5: Foreign Key Discovery

### Query (expected)
```sql
SELECT
  c.conname,
  c.contype,
  c.conrelid,
  c.confrelid,
  c.conkey,
  c.confkey
FROM pg_constraint c
WHERE c.conrelid = $1
  AND c.contype = 'f'
```

### Expected Response (for posts table)

| conname | contype | conrelid | confrelid | conkey | confkey |
|---------|---------|----------|-----------|--------|---------|
| posts_author_id_fkey | f | 16385 | 16384 | {2} | {1} |

### Notes
- `conrelid`: OID of table with FK
- `confrelid`: OID of referenced table
- `conkey`: columns in FK table
- `confkey`: columns in referenced table

---

## TC-6: Index Discovery

### Query (expected)
```sql
SELECT
  i.indexrelid,
  i.indrelid,
  i.indkey,
  i.indisunique,
  i.indisprimary,
  c.relname as indexname
FROM pg_index i
JOIN pg_class c ON c.oid = i.indexrelid
WHERE i.indrelid = $1
```

### Expected Response

| indexrelid | indrelid | indkey | indisunique | indisprimary | indexname |
|------------|----------|--------|-------------|--------------|-----------|
| 16400 | 16384 | 1 | t | t | users_pkey |
| 16401 | 16384 | 3 | t | f | users_email_key |

---

## TC-7: Unique Constraint Discovery

### Query (expected)
```sql
SELECT
  c.conname,
  c.contype,
  c.conkey
FROM pg_constraint c
WHERE c.conrelid = $1
  AND c.contype = 'u'
```

### Expected Response

| conname | contype | conkey |
|---------|---------|--------|
| users_email_key | u | {3} |

---

## TC-8: Default Values Discovery

### Query (expected)
```sql
SELECT
  d.adrelid,
  d.adnum,
  pg_get_expr(d.adbin, d.adrelid) as default_expr
FROM pg_attrdef d
WHERE d.adrelid = $1
```

### Expected Response

| adrelid | adnum | default_expr |
|---------|-------|--------------|
| 16384 | 1 | nextval('users_id_seq') |
| 16384 | 4 | CURRENT_TIMESTAMP |

### Notes
- IDENTITY columns show as `nextval('table_column_seq')`
- Default values expressed as PostgreSQL expressions

---

## Generated Schema Verification

### Input Table (IRIS)
```sql
CREATE TABLE SQLUser.TestTable (
    id INT IDENTITY PRIMARY KEY,
    name VARCHAR(255) NOT NULL,
    email VARCHAR(255) UNIQUE,
    active BIT DEFAULT 1,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

### Expected Drizzle Output
```typescript
// schema.ts
import { pgTable, serial, varchar, boolean, timestamp } from 'drizzle-orm/pg-core';

export const testTable = pgTable('test_table', {
  id: serial('id').primaryKey(),
  name: varchar('name', { length: 255 }).notNull(),
  email: varchar('email', { length: 255 }).unique(),
  active: boolean('active').default(true),
  createdAt: timestamp('created_at').defaultNow(),
});
```

---

## Error Conditions

### EC-1: Empty Database
**Scenario**: No user tables exist
**Expected**: Introspection succeeds with empty schema.ts

### EC-2: Missing pg_catalog table
**Scenario**: Query for unsupported catalog table
**Expected**: Empty result set (not error)

### EC-3: Connection Failure
**Scenario**: IRIS PGWire not running
**Expected**: Connection error from driver

---

## Performance Requirements

- Namespace query: < 10ms
- Tables query: < 50ms (for up to 100 tables)
- Columns query: < 20ms per table
- Constraints query: < 20ms per table
- Total introspection: < 30 seconds for 50-table database

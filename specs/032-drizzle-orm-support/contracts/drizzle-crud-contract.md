# Contract: Drizzle CRUD Operations

**Feature**: 032-drizzle-orm-support
**Date**: 2025-12-25

## Overview

This contract defines the expected behavior for Drizzle ORM CRUD operations against IRIS PGWire. All operations should work identically to native PostgreSQL from Drizzle's perspective.

---

## TC-1: INSERT with .returning()

### Input
```typescript
const result = await db.insert(users).values({
  name: 'Alice',
  email: 'alice@example.com'
}).returning();
```

### Generated SQL (from Drizzle)
```sql
INSERT INTO "users" ("name", "email")
VALUES ($1, $2)
RETURNING "id", "name", "email", "created_at"
```

### Expected Behavior
- IRIS PGWire intercepts RETURNING clause
- Executes INSERT without RETURNING
- Retrieves inserted row via LAST_IDENTITY() and post-SELECT
- Returns complete row with auto-generated ID

### Expected Result
```typescript
[{ id: 1, name: 'Alice', email: 'alice@example.com', createdAt: Date }]
```

### Test Assertion
```typescript
expect(result).toHaveLength(1);
expect(result[0].id).toBeGreaterThan(0);
expect(result[0].name).toBe('Alice');
```

---

## TC-2: SELECT with WHERE

### Input
```typescript
const result = await db.select()
  .from(users)
  .where(eq(users.id, 1));
```

### Generated SQL
```sql
SELECT "id", "name", "email", "created_at"
FROM "users"
WHERE "id" = $1
```

### Expected Behavior
- IRIS PGWire translates $1 to ?
- Executes against SQLUser schema
- Returns rows with correct type mapping

### Expected Result
```typescript
[{ id: 1, name: 'Alice', email: 'alice@example.com', createdAt: Date }]
```

---

## TC-3: UPDATE with .returning()

### Input
```typescript
const result = await db.update(users)
  .set({ name: 'Alice Smith' })
  .where(eq(users.id, 1))
  .returning();
```

### Generated SQL
```sql
UPDATE "users"
SET "name" = $1
WHERE "id" = $2
RETURNING "id", "name", "email", "created_at"
```

### Expected Behavior
- IRIS PGWire captures WHERE clause
- Executes UPDATE without RETURNING
- Retrieves updated row via post-SELECT using captured WHERE
- Returns updated row data

### Expected Result
```typescript
[{ id: 1, name: 'Alice Smith', email: 'alice@example.com', createdAt: Date }]
```

---

## TC-4: DELETE with .returning()

### Input
```typescript
const result = await db.delete(users)
  .where(eq(users.id, 1))
  .returning();
```

### Generated SQL
```sql
DELETE FROM "users"
WHERE "id" = $1
RETURNING "id", "name", "email", "created_at"
```

### Expected Behavior
- IRIS PGWire captures WHERE clause
- Pre-captures row data via SELECT before DELETE (row won't exist after)
- Executes DELETE
- Returns pre-captured row data

### Expected Result
```typescript
[{ id: 1, name: 'Alice Smith', email: 'alice@example.com', createdAt: Date }]
```

---

## TC-5: Transaction Support

### Input
```typescript
await db.transaction(async (tx) => {
  const user = await tx.insert(users).values({ name: 'Bob' }).returning();
  await tx.insert(posts).values({
    authorId: user[0].id,
    title: 'Hello'
  });
});
```

### Expected Behavior
- BEGIN sent at transaction start
- All operations execute within transaction
- COMMIT sent on success
- ROLLBACK sent on error

### Verification
```typescript
// After successful transaction
const users = await db.select().from(users);
const posts = await db.select().from(posts);
expect(users).toHaveLength(1);
expect(posts).toHaveLength(1);
```

---

## TC-6: Batch Insert

### Input
```typescript
const result = await db.insert(users).values([
  { name: 'User 1' },
  { name: 'User 2' },
  { name: 'User 3' }
]).returning();
```

### Expected Behavior
- Multiple rows inserted in single statement or batch
- All inserted rows returned with generated IDs

### Expected Result
```typescript
expect(result).toHaveLength(3);
result.forEach(r => expect(r.id).toBeGreaterThan(0));
```

---

## TC-7: Type Mapping Verification

### Test Data
```typescript
const testData = {
  intVal: 42,
  bigintVal: 9007199254740991n,
  textVal: 'Hello World',
  boolVal: true,
  timestampVal: new Date('2025-12-25T00:00:00Z'),
  decimalVal: '123.45'
};
```

### Expected Type Roundtrip
- Insert values → Read back → Types match original
- BigInt preserved (not truncated)
- Timestamps preserve timezone
- Decimals preserve precision

---

## Error Conditions

### EC-1: Constraint Violation

**Input**: Insert duplicate unique value
**Expected**: Error with constraint violation message
**Drizzle Handling**: Throws exception that can be caught

### EC-2: Foreign Key Violation

**Input**: Insert with non-existent foreign key
**Expected**: Error with foreign key violation message
**Drizzle Handling**: Throws exception that can be caught

### EC-3: Type Mismatch

**Input**: Insert string into integer column
**Expected**: Error with type mismatch message
**Drizzle Handling**: Throws exception that can be caught

---

## Performance Requirements

- INSERT with RETURNING: < 50ms (including emulation overhead)
- SELECT single row: < 20ms
- UPDATE with RETURNING: < 50ms
- DELETE with RETURNING: < 50ms
- Transaction overhead: < 10ms per BEGIN/COMMIT

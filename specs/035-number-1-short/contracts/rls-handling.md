# Contract: Row Level Security Statement Handling

**Feature**: 035-number-1-short  
**Version**: 1.0  
**Date**: 2026-01-17

## Overview

This contract defines how PostgreSQL Row Level Security (RLS) statements are handled for IRIS compatibility. All RLS statements are skipped with a no-op success response.

---

## Statement Patterns

### ENABLE ROW LEVEL SECURITY

**Pattern**: `ALTER TABLE ["schema".]"table" ENABLE ROW LEVEL SECURITY`

**Behavior**: Skip execution, return success.

**Examples**:
```sql
-- Input
ALTER TABLE "logs" ENABLE ROW LEVEL SECURITY;

-- Output: No SQL sent to IRIS
-- Response: CommandComplete with tag "ALTER TABLE"
```

### DISABLE ROW LEVEL SECURITY

**Pattern**: `ALTER TABLE ["schema".]"table" DISABLE ROW LEVEL SECURITY`

**Behavior**: Skip execution, return success.

**Examples**:
```sql
-- Input
ALTER TABLE "user_environment" DISABLE ROW LEVEL SECURITY;

-- Output: No SQL sent to IRIS
-- Response: CommandComplete with tag "ALTER TABLE"
```

### CREATE POLICY

**Pattern**: `CREATE POLICY "name" ON ["schema".]"table" ...`

**Behavior**: Skip execution, return success.

**Examples**:
```sql
-- Input
CREATE POLICY "users_policy" ON "users" FOR SELECT USING (user_id = current_user_id());

-- Output: No SQL sent to IRIS
-- Response: CommandComplete with tag "CREATE POLICY"
```

### DROP POLICY

**Pattern**: `DROP POLICY "name" ON ["schema".]"table"`

**Behavior**: Skip execution, return success.

**Examples**:
```sql
-- Input
DROP POLICY "users_policy" ON "users";

-- Output: No SQL sent to IRIS
-- Response: CommandComplete with tag "DROP POLICY"
```

---

## Detection Patterns

### Regex Patterns

```
ENABLE RLS:  ALTER\s+TABLE\s+.*\bENABLE\s+ROW\s+LEVEL\s+SECURITY\b
DISABLE RLS: ALTER\s+TABLE\s+.*\bDISABLE\s+ROW\s+LEVEL\s+SECURITY\b
CREATE POLICY: ^\s*CREATE\s+POLICY\s+
DROP POLICY: ^\s*DROP\s+POLICY\s+
```

### Case Sensitivity

All patterns are case-insensitive.

---

## Multi-Statement Handling

RLS statements may appear interleaved with other DDL in a batch:

```sql
CREATE TABLE logs (id INT);
ALTER TABLE logs ENABLE ROW LEVEL SECURITY;  -- Skip this
CREATE INDEX idx_logs ON logs(id);            -- Execute this
```

**Behavior**: Each statement processed independently. Skipped statements do not affect processing of other statements in the batch.

---

## Test Scenarios

| ID | Input | Expected Output | Verification |
|----|-------|-----------------|--------------|
| R-001 | `ALTER TABLE t ENABLE ROW LEVEL SECURITY` | Skip | No IRIS error, success response |
| R-002 | `ALTER TABLE t DISABLE ROW LEVEL SECURITY` | Skip | No IRIS error, success response |
| R-003 | `CREATE POLICY p ON t ...` | Skip | No IRIS error, success response |
| R-004 | `DROP POLICY p ON t` | Skip | No IRIS error, success response |
| R-005 | RLS in multi-statement batch | Other statements execute | Non-RLS statements succeed |
| R-006 | Schema-qualified table in RLS | Skip | Schema prefix handled |

---

## Rationale

IRIS does not support PostgreSQL Row Level Security. IRIS provides security through:
- Role-based access control
- Resource-based permissions
- SQL GRANT/REVOKE privileges

Skipping RLS statements is acceptable because:
1. Migrations complete successfully
2. IRIS has alternative security mechanisms
3. Per clarification: fail-safe skip approach confirmed

---

## Error Conditions

| Condition | Handling |
|-----------|----------|
| Malformed RLS statement | May pass through to IRIS if pattern doesn't match |
| RLS on non-existent table | Skipped (table existence not validated) |

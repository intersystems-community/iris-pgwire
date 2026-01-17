# Contract: Enum Type Handling

**Feature**: 035-number-1-short  
**Version**: 1.0  
**Date**: 2026-01-17

## Overview

This contract defines how PostgreSQL ENUM type statements are handled for IRIS compatibility.

---

## Statement Patterns

### CREATE TYPE ... AS ENUM

**Pattern**: `CREATE TYPE ["schema".]"name" AS ENUM ('value1', 'value2', ...)`

**Behavior**: Skip execution, register type name, return success.

**Examples**:
```sql
-- Input
CREATE TYPE "public"."permission_type" AS ENUM('admin', 'write', 'read');

-- Output: No SQL sent to IRIS
-- Side effect: Register "permission_type" in enum registry
-- Response: CommandComplete with tag "CREATE TYPE"
```

### DROP TYPE (for registered enums)

**Pattern**: `DROP TYPE ["schema".]"name"`

**Behavior**: If type is registered, skip execution and return success.

**Examples**:
```sql
-- Input (type previously registered)
DROP TYPE "public"."permission_type";

-- Output: No SQL sent to IRIS
-- Response: CommandComplete with tag "DROP TYPE"
```

---

## Column Type Translation

### Column Definition

**Pattern**: Column type matches registered enum name

**Behavior**: Replace enum type with `VARCHAR(64)`

**Examples**:
```sql
-- Input
"permission_type" "permission_type" NOT NULL

-- Output
"permission_type" VARCHAR(64) NOT NULL
```

### ALTER COLUMN SET DATA TYPE

**Pattern**: `ALTER COLUMN ... SET DATA TYPE "enum_type"`

**Behavior**: Replace enum type with `VARCHAR(64)`

**Examples**:
```sql
-- Input
ALTER TABLE "workspace_invitation" ALTER COLUMN "status" SET DATA TYPE "public"."workspace_invitation_status"

-- Output
ALTER TABLE "workspace_invitation" ALTER COLUMN "status" SET DATA TYPE VARCHAR(64)
```

---

## Enum Cast Handling

### Type Cast in Expression

**Pattern**: `'value'::"schema"."enum_type"` or `'value'::"enum_type"`

**Behavior**: Strip the cast, leaving only the value

**Examples**:
```sql
-- Input
ALTER TABLE "workspace_invitation" ALTER COLUMN "status" SET DEFAULT 'pending'::"public"."workspace_invitation_status"

-- Output
ALTER TABLE "workspace_invitation" ALTER COLUMN "status" SET DEFAULT 'pending'
```

```sql
-- Input
'webhook'::"notification_type"

-- Output
'webhook'
```

---

## Registry Behavior

### Registration

- Type name extracted from CREATE TYPE statement
- Schema qualifier stripped (`"public"."name"` → `name`)
- Stored as lowercase for case-insensitive matching
- Scoped to session/connection

### Lookup

- Column types checked against registry before translation
- Cast targets checked against registry before stripping
- Matching is case-insensitive

### Lifetime

- Registry cleared when connection closes
- No persistence across connections

---

## Test Scenarios

| ID | Input | Expected Output | Verification |
|----|-------|-----------------|--------------|
| E-001 | `CREATE TYPE "status" AS ENUM('a','b')` | Skip, register "status" | No IRIS error, registry contains "status" |
| E-002 | `CREATE TABLE t (c "status")` | `CREATE TABLE t (c VARCHAR(64))` | Table created with VARCHAR column |
| E-003 | `'val'::"public"."status"` | `'val'` | Cast stripped from expression |
| E-004 | `DROP TYPE "status"` | Skip | No IRIS error |
| E-005 | Schema-qualified enum | VARCHAR(64) | Schema prefix handled |
| E-006 | Quoted identifier enum | VARCHAR(64) | Quotes handled |

---

## Error Conditions

| Condition | Handling |
|-----------|----------|
| Malformed CREATE TYPE | Pass through to IRIS (let IRIS report error) |
| Unregistered type in column | Pass through (not an enum we know about) |
| Empty enum values | Skip as normal (registration still works) |

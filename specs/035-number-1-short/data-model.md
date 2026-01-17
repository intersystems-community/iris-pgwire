# Data Model: PostgreSQL DDL Compatibility (ENUM, RLS, Boolean Defaults)

**Feature**: 035-number-1-short  
**Date**: 2026-01-17

## Overview

This document describes the data structures and state management for the DDL compatibility feature. The primary entities are the Enum Type Registry and the Statement Classification system.

---

## Entities

### 1. Enum Type Registry

**Purpose**: Track registered PostgreSQL enum type names within a session to enable column type translation and cast stripping.

**Scope**: Session/connection level (not global)

**Attributes**:
| Attribute | Type | Description |
|-----------|------|-------------|
| type_names | Set[str] | Lowercase, unqualified enum type names |

**Operations**:
| Operation | Trigger | Effect |
|-----------|---------|--------|
| register | CREATE TYPE ... AS ENUM detected | Add type name to set |
| lookup | Column type or cast detected | Check if type is registered |
| clear | Connection close | Empty the set |

**Validation Rules**:
- Type names stored in lowercase for case-insensitive matching
- Schema qualifiers stripped (e.g., `"public"."status"` → `status`)
- Quoted identifiers unquoted (e.g., `"MyEnum"` → `myenum`)

---

### 2. Statement Classification

**Purpose**: Categorize incoming SQL statements for appropriate handling.

**Categories**:
| Category | Pattern | Action |
|----------|---------|--------|
| SKIP_ENUM | `CREATE TYPE ... AS ENUM` | Register type, return success |
| SKIP_DROP_TYPE | `DROP TYPE <registered>` | Return success if registered |
| SKIP_RLS_ENABLE | `ALTER TABLE ... ENABLE ROW LEVEL SECURITY` | Return success |
| SKIP_RLS_DISABLE | `ALTER TABLE ... DISABLE ROW LEVEL SECURITY` | Return success |
| SKIP_POLICY_CREATE | `CREATE POLICY ...` | Return success |
| SKIP_POLICY_DROP | `DROP POLICY ...` | Return success |
| TRANSLATE | DDL with enum types or boolean defaults | Apply translations |
| PASS_THROUGH | All other statements | No modification |

**State Transitions**:
```
Incoming SQL
    │
    ▼
┌─────────────────┐
│ Classify        │
└─────────────────┘
    │
    ├── SKIP_* ──────► Return success (no execution)
    │
    ├── TRANSLATE ──► Apply translations ──► Continue to IRIS
    │
    └── PASS_THROUGH ──► Continue to IRIS
```

---

### 3. Translation Result

**Purpose**: Capture the outcome of statement processing.

**Attributes**:
| Attribute | Type | Description |
|-----------|------|-------------|
| original_sql | str | Input SQL statement |
| processed_sql | str | Output SQL (may be empty for skipped) |
| was_skipped | bool | True if statement was skipped |
| skip_reason | str | Category name if skipped |
| translations_applied | List[str] | Names of translations performed |

---

## Relationships

```
┌─────────────────────┐
│  PGWireProtocol     │
│  (Connection)       │
└─────────────────────┘
         │
         │ owns
         ▼
┌─────────────────────┐
│  SQLTranslator      │
│  (Normalizer)       │
└─────────────────────┘
         │
         │ contains
         ▼
┌─────────────────────┐
│  EnumTypeRegistry   │
│  (Session-scoped)   │
└─────────────────────┘
```

---

## Data Flow

### CREATE TYPE Processing
```
Input: CREATE TYPE "public"."status" AS ENUM ('active', 'inactive')
    │
    ▼
1. Classify → SKIP_ENUM
    │
    ▼
2. Extract type name: "status" (lowercase, unqualified)
    │
    ▼
3. Register in EnumTypeRegistry
    │
    ▼
4. Return success (SQL not sent to IRIS)
```

### Column Type Translation
```
Input: CREATE TABLE users (id INT, status "status" NOT NULL)
    │
    ▼
1. Classify → TRANSLATE
    │
    ▼
2. Lookup "status" in EnumTypeRegistry → Found
    │
    ▼
3. Replace "status" with VARCHAR(64)
    │
    ▼
Output: CREATE TABLE users (id INT, status VARCHAR(64) NOT NULL)
```

### Boolean Default Translation
```
Input: ALTER TABLE users ADD COLUMN active boolean DEFAULT true
    │
    ▼
1. Classify → TRANSLATE
    │
    ▼
2. Detect DEFAULT true (not in string/comment)
    │
    ▼
3. Replace with DEFAULT 1
    │
    ▼
Output: ALTER TABLE users ADD COLUMN active BIT DEFAULT 1
    (Note: boolean→BIT handled by existing type mapping)
```

---

## Persistence

None. All state is in-memory and session-scoped. No database storage required.

---

## Validation Rules Summary

| Rule | Entity | Constraint |
|------|--------|------------|
| VR-001 | EnumTypeRegistry | Type names must be lowercase |
| VR-002 | EnumTypeRegistry | Schema qualifiers must be stripped |
| VR-003 | Statement Classification | SKIP categories must not execute SQL |
| VR-004 | Translation Result | was_skipped=true requires skip_reason |
| VR-005 | Boolean Translation | Must not modify string literals |
| VR-006 | Boolean Translation | Must not modify comments |
